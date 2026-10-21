import koffi from 'koffi';
import { randomUUID } from 'node:crypto';
import { constants, openSync, closeSync, fstatSync, ftruncateSync, fsyncSync, readSync, writeSync, realpathSync, lstatSync } from 'node:fs';
import { isAbsolute, relative, resolve, sep, dirname, basename } from 'node:path';

let native: { openAt: (dir: number, name: string, flags: number, mode: number) => number;
  mkdirAt: (dir: number, name: string, mode: number) => number; list: (fd: number, max: number) => string[];
  renameAt: (dir: number, source: string, target: string) => number;
  unlinkAt: (dir: number, name: string) => number; close: (fd: number) => void } | undefined;
function systemFiles() {
  if (process.platform !== 'darwin' || process.arch !== 'arm64') throw Error('原生文件映射尚未验证此平台');
  if (!native) {
    const library = koffi.load('/usr/lib/libSystem.B.dylib');
    const open = library.func('int openat(int dirfd, const char *path, int flags, ...)');
    const mkdir = library.func('int mkdirat(int dirfd, const char *path, unsigned int mode)');
    const rename = library.func('int renameat(int fromfd, const char *from, int tofd, const char *to)');
    const unlink = library.func('int unlinkat(int dirfd, const char *path, int flags)');
    const dup = library.func('int dup(int fd)'), fdopendir = library.func('void *fdopendir(int fd)');
    const readdir = library.func('void *readdir(void *dir)'), closedir = library.func('int closedir(void *dir)');
    const errorPointer = library.func('int *__error(void)');
    const close = library.func('int close(int fd)');
    native = { openAt: (dir, name, flags, mode) => Number(open(dir, name, flags, 'int', mode)),
      mkdirAt: (dir, name, mode) => Number(mkdir(dir, name, mode)),
      renameAt: (dir, source, target) => Number(rename(dir, source, dir, target)),
      unlinkAt: (dir, name) => unlink(dir, name, 0) as number,
      close: fd => { if (close(fd) !== 0) throw Error('原生文件句柄关闭失败'); },
      list: (fd, max) => {
        const copy = Number(dup(fd)); if (copy < 0) throw Error('目录句柄不可复制');
        const dir = fdopendir(copy); if (!dir) { close(copy); throw Error('目录不可枚举'); }
        const names: string[] = [];
        try {
          for (;;) {
            const error = errorPointer(); koffi.encode(error, 'int', 0);
            const entry = readdir(dir);
            if (!entry) {
              if (koffi.decode(error, 'int') !== 0) throw Error('目录枚举中断');
              break;
            }
            // Darwin arm64 struct dirent: two uint64, reclen/nlen uint16, type uint8, name.
            const length = Number(koffi.decode(entry, 18, 'uint16_t'));
            const record = Number(koffi.decode(entry, 16, 'uint16_t'));
            if (length < 1 || length > 1023 || record < 22 + length) throw Error('目录记录不符合平台格式');
            const name = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(koffi.decode(entry, 21, 'uint8_t', length) as number[]));
            if (name === '.' || name === '..') continue;
            if (name.includes('/') || name.includes('\0')) throw Error('目录名称无效');
            names.push(name); if (names.length > max) throw Error('目录文件数量超过限制');
          }
          return names;
        } finally { closedir(dir); }
      } };
  }
  return native;
}
const beneath = (path: string, root: string): boolean => path === root || path.startsWith(root + sep);
function canonicalFuturePath(path: string): string {
  let cursor = resolve(path); const missing: string[] = [];
  for (;;) {
    try { return resolve(realpathSync(cursor), ...missing.reverse()); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT' || dirname(cursor) === cursor) throw error;
      missing.push(basename(cursor)); cursor = dirname(cursor);
    }
  }
}
export class WorkspaceFiles {
  readonly root: string;
  private readonly protectedRoots: string[];
  constructor(root: string, protectedRoots: string[]) {
    this.root = realpathSync(root); this.protectedRoots = protectedRoots.map(path => canonicalFuturePath(path).toLowerCase());
  }
  path(value: string): string {
    if (!value || value.includes('\0') || value.includes('\\') || value.includes(':') || value.startsWith('//')) throw Error('路径格式不安全');
    const target = resolve(this.root, value), lower = target.toLowerCase();
    const parts = (isAbsolute(value) ? relative(this.root, value) : value).split('/').filter(part => part && part !== '.');
    if (!beneath(target, this.root) || !parts.length || parts.some(part => part === '..' ||
      ['.git', '.ssh', '.aws'].includes(part.toLowerCase()) || part.toLowerCase().startsWith('.env') || part.toLowerCase().includes('credential'))) {
      throw Error('路径越界或属于私密资料');
    }
    if (['skills','memory','user.md','soul.md','system.md','agents.md'].includes(parts[0]!.toLowerCase()) ||
      this.protectedRoots.some(root => beneath(lower, root))) throw Error('应用核心、评测与知识资料须通过专用接口操作');
    return parts.join('/');
  }
  checkNoSymlink(value: string): string {
    const path = this.path(value); let cursor = this.root;
    for (const part of path.split('/')) {
      cursor = resolve(cursor, part);
      try { if (lstatSync(cursor).isSymbolicLink()) throw Error('路径不能经过符号链接'); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    }
    return resolve(this.root, path);
  }
  private parent<T>(value: string, action: (fd: number, leaf: string) => T): T {
    const parts = this.path(value).split('/'), api = systemFiles();
    let directory = openSync(this.root, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    let nativeDirectory = false;
    const closeDirectory = () => nativeDirectory ? api.close(directory) : closeSync(directory);
    try {
      for (const part of parts.slice(0, -1)) {
        const next = api.openAt(directory, part, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW, 0);
        if (next < 0) throw Error('父目录不可用或包含符号链接');
        closeDirectory(); directory = next; nativeDirectory = true;
      }
      return action(directory, parts.at(-1)!);
    } finally { closeDirectory(); }
  }
  readBytes(value: string, limit = 100000): Buffer {
    return this.parent(value, (directory, leaf) => {
      const fd = systemFiles().openAt(directory, leaf, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0);
      if (fd < 0) throw Error('文件不可读取');
      try {
        const info = fstatSync(fd);
        if (!info.isFile() || info.nlink !== 1 || info.size > limit) throw Error('文件类型、链接数或大小不符合要求');
        const data = Buffer.alloc(limit + 1); let total = 0;
        while (total <= limit) { const count = readSync(fd, data, total, limit + 1 - total, null); if (!count) break; total += count; }
        if (total > limit) throw Error('文件超过读取限制'); return data.subarray(0, total);
      } finally { systemFiles().close(fd); }
    });
  }
  read(value: string): string { return new TextDecoder('utf-8', { fatal: true }).decode(this.readBytes(value)); }
  writeBytes(value: string, data: Buffer, exclusive = false): void {
    if (data.length > 32 * 1024 * 1024) throw Error('文件超过写入限制');
    this.parent(value, (directory, leaf) => {
      const fd = systemFiles().openAt(directory, leaf, constants.O_WRONLY | constants.O_CREAT | constants.O_NOFOLLOW |
        constants.O_NONBLOCK | (exclusive ? constants.O_EXCL : 0), 0o600);
      if (fd < 0) throw Error('文件不可写入或目标已存在');
      try {
        const info = fstatSync(fd);
        if (!info.isFile() || info.nlink !== 1) throw Error('只能写入无硬链接的普通文件');
        ftruncateSync(fd, 0); let offset = 0;
        while (offset < data.length) {
          const written = writeSync(fd, data, offset, data.length - offset);
          if (!written) throw Error('文件写入未取得进展'); offset += written;
        }
        fsyncSync(fd);
      } finally { systemFiles().close(fd); }
    });
  }
  write(value: string, content: string): void { this.writeBytes(value, Buffer.from(content)); }
  atomicWrite(value: string, content: string): void {
    const data = Buffer.from(content);
    if (data.length > 32 * 1024 * 1024) throw Error('文件超过写入限制');
    this.parent(value, (directory, leaf) => {
      const api = systemFiles(), temporary = `.projection-${randomUUID()}`;
      const fd = api.openAt(directory, temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      if (fd < 0) throw Error('无法创建投影临时文件');
      try {
        try {
          let offset = 0;
          while (offset < data.length) {
            const count = writeSync(fd, data, offset, data.length - offset);
            if (!count) throw Error('投影写入未取得进展'); offset += count;
          }
          fsyncSync(fd);
        } finally { api.close(fd); }
        if (api.renameAt(directory, temporary, leaf) !== 0) throw Error('无法替换投影文件');
        fsyncSync(directory);
      } finally { api.unlinkAt(directory, temporary); }
    });
  }
  createDirectory(value: string): void {
    this.parent(value, (directory, leaf) => {
      if (systemFiles().mkdirAt(directory, leaf, 0o700) !== 0) throw Error('目录已存在或无法创建');
    });
  }
  removeFile(value: string): void {
    this.parent(value,(directory,leaf) => {
      if (systemFiles().unlinkAt(directory,leaf) !== 0) throw Error('文件无法移除');
    });
  }
  ensureDirectories(value: string): void {
    const parts = this.path(value).split('/'); const api = systemFiles();
    let directory = openSync(this.root, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    let nativeDirectory = false;
    const closeDirectory = () => nativeDirectory ? api.close(directory) : closeSync(directory);
    try {
      for (const part of parts) {
        api.mkdirAt(directory, part, 0o700);
        const next = api.openAt(directory, part, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW, 0);
        if (next < 0) throw Error('输出目录不可创建或包含符号链接');
        closeDirectory(); directory = next; nativeDirectory = true;
      }
    } finally { closeDirectory(); }
  }
  list(value: string, max = 100): string[] {
    return this.parent(value, (directory, leaf) => {
      const fd = systemFiles().openAt(directory, leaf, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW, 0);
      if (fd < 0) throw Error('目录不可读取');
      try { return systemFiles().list(fd, max); } finally { systemFiles().close(fd); }
    });
  }
  signature(value: string): string {
    return this.parent(value, (directory, leaf) => {
      const fd = systemFiles().openAt(directory, leaf, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0);
      if (fd < 0) throw Error('来源不可读取');
      try {
        const info = fstatSync(fd, { bigint: true });
        if (!info.isFile() || info.nlink !== 1n || info.size > 100000n) throw Error('来源不是受限普通文件');
        return [info.dev,info.ino,info.size,info.mtimeNs,info.ctimeNs].join(':');
      } finally { systemFiles().close(fd); }
    });
  }
}
