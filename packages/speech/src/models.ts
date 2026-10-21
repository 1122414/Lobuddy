import { createHash, randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, mkdir, open, rename, rm } from 'node:fs/promises';
import { dirname, join, resolve, parse } from 'node:path';
import { MODEL, VAD } from './manifest.js';
const assets = [...MODEL.files.map(file => ({ ...file,name: 'whisper-small/' + file.name })),{ ...VAD,name: 'silero.onnx' }];
async function directory(path: string) {
  const target = resolve(path),root = parse(target).root;
  let cursor = root;
  for (const part of target.slice(root.length).split('/').filter(Boolean)) {
    cursor = join(cursor,part);
    await mkdir(cursor,{ mode: 0o700 }).catch(error => { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; });
    const info = await lstat(cursor); if (!info.isDirectory() || info.isSymbolicLink()) throw Error('模型目录不可用');
  }
}
async function verify(path: string,asset: typeof assets[number]) {
  const file = await open(path,constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await file.stat(); if (!stat.isFile() || stat.size !== asset.size || stat.nlink !== 1) throw Error('模型文件校验失败');
    const hash = createHash('sha256'); for await (const chunk of file.createReadStream({ autoClose: false })) hash.update(chunk);
    if (hash.digest('hex') !== asset.sha256) throw Error('模型文件校验失败');
  } finally { await file.close(); }
}
export async function modelsReady(root: string): Promise<boolean> {
  try {
    for (const path of [root,join(root,'whisper-small'),join(root,'whisper-small/onnx')]) {
      const info = await lstat(path); if (!info.isDirectory() || info.isSymbolicLink()) return false;
    }
    for (const asset of assets) await verify(join(root,asset.name),asset); return true;
  } catch { return false; }
}
export async function downloadModels(root: string,signal: AbortSignal): Promise<void> {
  await directory(root);
  for (const asset of assets) {
    signal.throwIfAborted(); const path = join(root,asset.name); await directory(dirname(path));
    try { await verify(path,asset); continue; } catch { /* Explicit download repairs incomplete files. */ }
    const partial = path + '.' + randomUUID() + '.partial';
    const file = await open(partial,'wx',0o600);
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      let url = new URL(asset.url),response: Response | undefined;
      for (let redirect = 0; redirect < 6; redirect++) {
        if (url.protocol !== 'https:' || url.port && url.port !== '443' || url.username || url.password ||
          !['huggingface.co','raw.githubusercontent.com'].includes(url.hostname) && !url.hostname.endsWith('.hf.co')) throw Error('模型下载地址无效');
        response = await fetch(url,{ redirect: 'manual',signal: AbortSignal.any([signal,AbortSignal.timeout(180000)]) });
        if (![301,302,303,307,308].includes(response.status)) break;
        await response.body?.cancel(); url = new URL(response.headers.get('location') ?? '',url); response = undefined;
      }
      if (!response?.ok || !response.body) throw Error('模型下载失败');
      reader = response.body.getReader(); let count = 0; const hash = createHash('sha256');
      for (;;) {
        const part = await reader.read(); if (part.done) break; count += part.value.byteLength;
        if (count > asset.size) throw Error('模型下载超出固定大小');
        hash.update(part.value); await file.writeFile(part.value);
      }
      if (count !== asset.size || hash.digest('hex') !== asset.sha256) throw Error('模型下载校验失败');
      await file.sync(); await file.close(); signal.throwIfAborted(); await rename(partial,path);
    } finally { await reader?.cancel().catch(() => {}); await file.close().catch(() => {}); await rm(partial,{ force: true }); }
  }
  if (!await modelsReady(root)) throw Error('模型下载校验失败');
}
