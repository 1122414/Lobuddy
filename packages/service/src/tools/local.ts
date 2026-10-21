import { homedir } from 'node:os';
import { lstatSync, readdirSync, realpathSync } from 'node:fs';
import { join, extname, basename } from 'node:path';
import { spawn } from 'node:child_process';
const DOCUMENTS = new Set(['.txt','.md','.pdf','.docx','.xlsx','.pptx','.png','.jpg','.jpeg','.webp','.gif']);
type Candidate = { path: string; signature: string; source: string };
const signature = (path: string) => {
  const stat = lstatSync(path, { bigint: true }); if (stat.isSymbolicLink()) throw Error('候选不能为符号链接');
  return [stat.dev, stat.ino, stat.mtimeNs].join(':');
};
export class LocalOpen {
  private readonly candidates = new Map<string, Candidate>();
  constructor(private readonly workspace: string, private readonly home = homedir()) {}
  resolve(query: string): { path: string; name: string; source: string }[] {
    this.candidates.clear(); if (!query.trim()) throw Error('请输入要查找的应用或文件名称');
    const roots = [['工作区',this.workspace],['桌面',join(this.home,'Desktop')],['应用程序','/Applications'],['系统应用','/System/Applications'],['个人应用',join(this.home,'Applications')]];
    for (const [source, root] of roots) {
      try {
        const info = lstatSync(root!); if (info.isSymbolicLink() || !info.isDirectory()) continue;
        for (const name of readdirSync(root!).slice(0, 200)) {
          if (name.startsWith('.') || !basename(name, extname(name)).toLowerCase().includes(query.toLowerCase())) continue;
          const path = join(root!, name), stat = lstatSync(path), extension = extname(name).toLowerCase();
          if (stat.isSymbolicLink() || !((extension === '.app' && stat.isDirectory()) || (DOCUMENTS.has(extension) && stat.isFile()))) continue;
          const canonical = realpathSync(path); this.candidates.set(canonical, { path: canonical, signature: signature(canonical), source: source! });
          if (this.candidates.size >= 10) return this.describe();
        }
      } catch { continue; }
    }
    return this.describe();
  }
  private describe() { return [...this.candidates.values()].map(item => ({ path: item.path, name: basename(item.path, extname(item.path)), source: item.source })); }
  validate(path: string): string {
    const item = this.candidates.get(path);
    if (!item || signature(path) !== item.signature) throw Error('只能打开本轮查找且未变化的候选');
    return item.path;
  }
}
export async function openNative(path: string, signal: AbortSignal): Promise<void> {
  if (process.platform !== 'darwin') throw Error('当前平台尚未完成本地打开验收');
  signal.throwIfAborted(); const combined = AbortSignal.any([signal, AbortSignal.timeout(10_000)]);
  const child = spawn('/usr/bin/open', [path], { stdio: 'ignore', signal: combined,
    env: { HOME: homedir(), PATH: '/usr/bin:/bin', LANG: 'en_US.UTF-8' } });
  await new Promise<void>((resolve, reject) => {
    child.once('error', () => reject(Error('本地打开已取消或失败')));
    child.once('exit', code => code === 0 ? resolve() : reject(Error('系统未能打开所选项目')));
  });
}
