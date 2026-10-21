import { constants } from 'node:fs';
import { open, mkdir, rename, unlink, lstat, readdir, realpath } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { StorageError } from './database.js';

export async function readPrivate(path: string, maxBytes = 1024 * 1024): Promise<Buffer> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > maxBytes) throw new StorageError('文件类型或大小不符合要求');
    return await handle.readFile();
  } finally { await handle.close(); }
}
export async function atomicPrivateWrite(path: string, bytes: Uint8Array): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  try { if (!(await lstat(path)).isFile()) throw new StorageError('目标不是普通文件'); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
  const temporary = join(dirname(path), `.lobuddy-write-${randomUUID()}`);
  const handle = await open(temporary, 'wx', 0o600);
  try {
    try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
    await rename(temporary, path);
    const directory = await open(dirname(path), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  } finally { await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}
export async function hashFile(path: string): Promise<string> {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    if (!(await handle.stat()).isFile()) throw new StorageError('备份只接受普通文件');
    const hash = createHash('sha256');
    for await (const chunk of handle.createReadStream({ autoClose: false })) hash.update(chunk);
    return hash.digest('hex');
  } finally { await handle.close(); }
}
export function relativeChild(base: string, name: string): string {
  if (isAbsolute(name) || name.includes('\0') || name.includes('\\') || name.split('/').some(part => !part || part === '..' || part === '.')) {
    throw new StorageError('备份文件路径无效');
  }
  const path = resolve(base, name);
  if (!path.startsWith(resolve(base) + sep)) throw new StorageError('备份路径超出目录');
  return path;
}
export async function enumerateFiles(base: string, subdirectory = ''): Promise<string[]> {
  const directory = join(base, subdirectory);
  if (!(await lstat(directory)).isDirectory()) throw new StorageError('备份目录不是普通目录');
  const files: string[] = [];
  for (const entry of await readdir(directory)) {
    const name = subdirectory ? `${subdirectory}/${entry}` : entry;
    const stat = await lstat(relativeChild(base, name));
    if (stat.isDirectory()) files.push(...await enumerateFiles(base, name));
    else if (stat.isFile()) files.push(name);
    else throw new StorageError('备份包含符号链接或特殊文件');
  }
  return files.sort();
}
export async function freshDestination(destination: string, sources: string[]): Promise<string> {
  const absolute = resolve(destination);
  await mkdir(dirname(absolute), { recursive: true, mode: 0o700 });
  const target = join(await realpath(dirname(absolute)), absolute.split(sep).at(-1)!);
  for (const source of sources) {
    const delta = relative(await realpath(source), target);
    if (!delta || (!delta.startsWith(`..${sep}`) && delta !== '..' && !isAbsolute(delta))) throw new StorageError('目标不能位于源目录内');
  }
  try { await lstat(target); throw new StorageError('目标已存在，未覆盖资料'); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
  return target;
}
