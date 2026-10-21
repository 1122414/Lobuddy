import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pcm16Mono } from './speech-probe.js';

const destination = resolve(process.argv[2] ?? '.local-upgrade/ts-corpus');
const output = resolve(process.argv[3] ?? 'qualification/ts-runtime/corpus-manifest.json');
await mkdir(destination, { recursive: true });
const base = 'https://huggingface.co/datasets/FluidInference/fleurs-full/resolve/1cca811bb8ea4d370345f108f00518167040282c/cmn_hans_cn/';
async function download(url: string): Promise<Buffer> {
  const response = await fetch(url, { signal: AbortSignal.timeout(30_000) });
  assert.ok(response.ok, `Corpus fetch returned ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  assert.ok(bytes.length <= 4_000_000, 'Unexpected corpus file size');
  return bytes;
}
type Case = { id: string; file: string; text: string; sha256: string; seconds: number;
  source: string; license: string; tags: string[]; derivedFrom?: string };
const cases: Case[] = [];
async function add(id: string, bytes: Buffer, text: string, source: string, license: string, tags: string[], derivedFrom?: string) {
  const audio = pcm16Mono(bytes);
  const file = `${id}.wav`;
  await writeFile(join(destination, file), bytes);
  const item = { id, file, text, source, license, tags, seconds: audio.length / 16_000,
    sha256: createHash('sha256').update(bytes).digest('hex'), ...(derivedFrom ? { derivedFrom } : {}) };
  cases.push(item);
}
const references = (await download(base + 'cmn_hans_cn.trans.txt')).toString('utf8').trim().split('\n');
for (const line of references) {
  if (cases.length >= 80) break;
  const separator = line.indexOf(' ');
  const id = line.slice(0, separator);
  assert.match(id, /^cmn_hans_cn_\d+$/);
  const text = line.slice(separator + 1).replaceAll(' ', '');
  const bytes = await download(base + id + '.wav');
  // Bound clips without clipping audio or reference text.
  if (bytes.length > 960_100) continue;
  await add(id, bytes, text, base + id + '.wav', 'CC-BY-4.0',
    ['mandarin', ...(/\d/.test(text) ? ['numbers'] : []), ...(/[a-z]/i.test(text) ? ['mixed-language'] : [])]);
  if (cases.length % 20 === 0) console.log(`Downloaded ${cases.length} Mandarin clips`);
}
const viewer = 'https://datasets-server.huggingface.co/rows?dataset=lianghsun%2Fzh-taiwan&config=test&split=train&offset=0&length=28';
const rows = JSON.parse((await download(viewer)).toString('utf8')) as {
  rows: { row_idx: number; row: { normalized_text: string; audio: { src: string }[] } }[];
};
assert.equal(rows.rows.length, 28);
for (const item of rows.rows) {
  const url = new URL(item.row.audio[0]!.src);
  assert.equal(url.origin, 'https://datasets-server.huggingface.co');
  assert.ok(url.pathname.includes('/92a37d1a58d70946b07348634eab6c271a35e3bb/'));
  await add(`taiwan-${item.row_idx}`, await download(url.href), item.row.normalized_text,
    url.origin + url.pathname, 'Apache-2.0', ['taiwan-source', ...(/[a-z]/i.test(item.row.normalized_text) ? ['mixed-language'] : [])]);
}
assert.equal(cases.length, 108);
await writeFile(output, JSON.stringify({ version: 1,
  attribution: [
    { author: 'Google FLEURS; FluidInference WAV mirror', license: 'CC-BY-4.0',
      original: 'https://huggingface.co/datasets/google/fleurs',
      mirror: 'https://huggingface.co/datasets/FluidInference/fleurs-full', revision: '1cca811bb8ea4d370345f108f00518167040282c' },
    { author: 'ivanzhu109; Liang Hsun Huang format mirror', license: 'Apache-2.0',
      original: 'https://huggingface.co/datasets/ivanzhu109/zh-taiwan',
      mirror: 'https://huggingface.co/datasets/lianghsun/zh-taiwan', revision: '92a37d1a58d70946b07348634eab6c271a35e3bb' },
  ],
  limitations: ['Taiwan dataset lacks speaker demographics; provenance is not accent certification.',
    'Pause and controlled-noise variants still need to be added before full qualification.'], cases,
}, null, 2) + '\n');
console.log('Prepared 108 source clips; no ASR scores have been computed.');
