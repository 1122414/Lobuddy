import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, basename } from 'node:path';
import type { WorkspaceFiles } from './files.js';

const FLAGS: Record<string, readonly string[]> = { ls: ['-l','-a','-la','-al','-h','-lh'], cat: ['-n'],
  head: ['-n'], tail: ['-n'], wc: ['-l','-w','-c'], pwd: [], echo: [], mkdir: ['-p'], touch: [], cp: ['-n'], mv: ['-n'], rm: [] };
export function commandArguments(command: string, files: WorkspaceFiles): string[] {
  if (!command || /[\0\r\n;&|`$<>()]/u.test(command)) throw Error('命令包含未允许的语法');
  const args: string[] = []; let token = '', quote = '', started = false;
  for (let i = 0; i < command.length; i++) {
    const char = command[i]!;
    if (char === '\\' && quote !== "'") {
      if (++i >= command.length) throw Error('命令转义不完整');
      if (quote === '"' && !['"', '\\'].includes(command[i]!)) token += '\\';
      token += command[i]; started = true; continue;
    }
    if (quote) { if (char === quote) quote = ''; else token += char; started = true; continue; }
    if (char === '"' || char === "'") { quote = char; started = true; continue; }
    if (/\s/u.test(char)) { if (started) { args.push(token); token = ''; started = false; } continue; }
    token += char; started = true;
  }
  if (quote) throw Error('命令引号不完整'); if (started) args.push(token);
  const name = args[0], flags = name ? FLAGS[name] : undefined;
  if (!name || !flags) throw Error('命令未完成安全映射');
  for (let i = 1; i < args.length; i++) {
    const value = args[i]!;
    if (value.startsWith('-')) { if (value !== '--' && !flags.includes(value)) throw Error('命令选项未完成安全映射'); continue; }
    if (name === 'echo' || (args[i - 1] === '-n' && /^\d+$/.test(value)) || (value === '.' && ['ls','pwd'].includes(name))) continue;
    files.checkNoSymlink(value);
  }
  const executable = ['/usr/bin','/bin'].map(root => join(root, name)).find(path => existsSync(path));
  if (!executable) throw Error('系统未安装该命令');
  return [executable, ...args.slice(1)];
}
export async function runCommand(args: string[], workspace: string, limit: number, timeoutMs: number, signal: AbortSignal): Promise<string> {
  signal.throwIfAborted();
  if (!args[0] || !FLAGS[basename(args[0])]) throw Error('命令不可执行');
  const child = spawn(args[0], args.slice(1), { cwd: workspace, detached: true, stdio: ['ignore','pipe','pipe'],
    env: { PATH: '/usr/bin:/bin', LANG: 'en_US.UTF-8', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_PAGER: 'cat' } });
  let size = 0, truncated = false; const chunks: Buffer[] = [];
  const capture = (block: Buffer) => { const remaining = limit * 4 - size; chunks.push(block.subarray(0, Math.max(0, remaining))); size += Math.min(remaining, block.length); truncated ||= block.length > remaining; };
  child.stdout.on('data', capture); child.stderr.on('data', capture);
  const kill = () => { if (child.pid) { try { process.kill(-child.pid, 'SIGKILL'); } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error; } } };
  const controller = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]);
  controller.addEventListener('abort', kill, { once: true });
  try {
    const code = await new Promise<number | null>((resolve, reject) => { child.once('error', () => reject(Error('本地命令无法启动'))); child.once('close', resolve); });
    controller.throwIfAborted();
    const output = [...Buffer.concat(chunks).toString('utf8')].slice(0, limit).join('');
    return `退出码 ${code}\n${output}${truncated ? '\n[结果已截断]' : ''}`;
  } finally { controller.removeEventListener('abort', kill); kill(); }
}
