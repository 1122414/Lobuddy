import { DatabaseSync, backup as sqliteBackup } from 'node:sqlite';
import { chmod, copyFile, lstat, mkdir, mkdtemp, readdir, rename, rm, realpath } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash, randomUUID } from 'node:crypto';
import { basename, dirname, join, resolve } from 'node:path';
import { BackupManifestSchema, ImportMarkerSchema, type BackupManifest } from '@lobuddy/contracts';
import { Store, inspectDatabase, StorageError, STORAGE_VERSION, sealSnapshot } from './database.js';
import { atomicPrivateWrite, enumerateFiles, freshDestination, hashFile, readPrivate, relativeChild } from './files.js';
import { recoverImportedWork, relocateReferences, validateStoredJson } from './import-records.js';
const WORKSPACE_ASSETS = ['skills', 'memory', 'USER.md', 'SOUL.md', 'SYSTEM.md', 'AGENTS.md'];
const SKIP_DATA = new Set(['lobuddy.db', 'lobuddy.db-wal', 'lobuddy.db-shm', 'backups', 'service.lock',
  'execution.lock.sqlite', 'execution.lock.sqlite-journal']);
const execute = promisify(execFile);

async function exists(path: string): Promise<boolean> {
  try { await lstat(path); return true; } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false; throw error; }
}
export async function requireStopped(data: string): Promise<void> {
  // Older Python releases own flock, not the new SQLite lease. Open handles are a conservative veto.
  const locks = ['service.lock', 'execution.lock.sqlite'];
  for (const name of locks) {
    const path = join(resolve(data), name);
    if (!await exists(path)) continue;
    if (process.platform !== 'darwin') throw new StorageError('本平台尚未验证旧进程停机检查');
    try {
      const { stdout } = await execute('/usr/sbin/lsof', ['-F', 'p', '--', path], { timeout: 5000, maxBuffer: 65536,
        env: { PATH: '/usr/bin:/bin' } });
      if (/^p\d+/m.test(stdout)) throw new StorageError('请退出使用该资料的应用后重试');
      throw new StorageError('无法确认旧进程已退出');
    } catch (error) {
      const failure = error as Error & { code?: number; stdout?: string; stderr?: string };
      if (failure.code !== 1 || failure.stdout || failure.stderr) throw new StorageError('旧资料仍在使用或停机检查失败');
    }
  }
  const home = join(data, 'dsh-home');
  if (await exists(home)) for (const name of await readdir(home)) {
    if (!name.startsWith('bridge-')) continue;
    const ready = join(home, name, 'ready.json');
    if (!await exists(ready)) continue;
    const state = JSON.parse((await readPrivate(ready, 65536)).toString()) as { pid?: unknown };
    if (!Number.isSafeInteger(state.pid) || Number(state.pid) <= 0) throw new StorageError('引擎状态无法校验');
    try { process.kill(Number(state.pid), 0); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ESRCH') continue; throw new StorageError('引擎状态无法校验'); }
    throw new StorageError('请先退出 DSH 引擎再备份');
  }
}
async function copyTree(source: string, target: string): Promise<void> {
  const stat = await lstat(source);
  if (stat.isDirectory()) {
    await mkdir(target, { recursive: true, mode: 0o700 });
    for (const entry of await readdir(source)) await copyTree(join(source, entry), join(target, entry));
  } else if (stat.isFile()) {
    await mkdir(dirname(target), { recursive: true, mode: 0o700 });
    // Open/hash checks reject leaf symlinks before and after copying.
    const before = await hashFile(source);
    await copyFile(source, target); await chmod(target, 0o600);
    if (before !== await hashFile(target) || before !== await hashFile(source)) throw new StorageError('备份时资料发生变化');
  } else throw new StorageError('备份包含符号链接或特殊文件');
}
export async function createBackup(data: string, workspace: string, destination: string): Promise<BackupManifest> {
  data = resolve(data); workspace = resolve(workspace);
  destination = await freshDestination(destination, [data, workspace]);
  await requireStopped(data);
  const directory = await mkdtemp(join(dirname(destination), '.lobuddy-backup-'));
  const stage = join(directory, 'snapshot');
  try {
    await mkdir(join(stage, 'data'), { recursive: true, mode: 0o700 });
    await mkdir(join(stage, 'workspace'), { mode: 0o700 });
    const path = join(data, 'lobuddy.db');
    if (!(await lstat(path)).isFile()) throw new StorageError('源数据库不是普通文件');
    const source = new DatabaseSync(path, { readOnly: true });
    try { inspectDatabase(source); validateStoredJson(source); await sqliteBackup(source, join(stage, 'data/lobuddy.db')); }
    finally { source.close(); }
    await chmod(join(stage, 'data/lobuddy.db'), 0o600);
    // Read-only validation of a WAL archive can still create sidecars and change its file inventory.
    sealSnapshot(join(stage, 'data/lobuddy.db'));
    for (const name of await readdir(data)) if (!SKIP_DATA.has(name)) await copyTree(join(data, name), join(stage, 'data', name));
    for (const name of WORKSPACE_ASSETS) if (await exists(join(workspace, name))) await copyTree(join(workspace, name), join(stage, 'workspace', name));
    const files: Record<string, string> = {};
    for (const name of await enumerateFiles(stage)) files[name] = await hashFile(relativeChild(stage, name));
    const manifest: BackupManifest = { format: 1, identity: randomUUID(), source_data: data,
      source_workspace: workspace, created_at: new Date().toISOString(), files };
    await atomicPrivateWrite(join(stage, 'manifest.json'), Buffer.from(JSON.stringify(manifest, null, 2)));
    await requireStopped(data); await freshDestination(destination, [data, workspace]);
    await rename(stage, destination); return manifest;
  } finally { await rm(directory, { recursive: true, force: true }); }
}
export async function verifyBackup(path: string): Promise<BackupManifest> {
  const manifest = BackupManifestSchema.parse(JSON.parse((await readPrivate(join(path, 'manifest.json'))).toString()));
  if (!manifest.files['data/lobuddy.db']) throw new StorageError('备份缺少数据库');
  const actual = (await enumerateFiles(path)).filter(name => name !== 'manifest.json');
  if (JSON.stringify(actual) !== JSON.stringify(Object.keys(manifest.files).sort())) throw new StorageError('备份文件清单不一致');
  for (const [name, hash] of Object.entries(manifest.files)) {
    if ((!name.startsWith('data/') && !name.startsWith('workspace/')) || await hashFile(relativeChild(path, name)) !== hash) throw new StorageError('备份路径或内容校验失败');
  }
  const db = new DatabaseSync(join(path, 'data/lobuddy.db'), { readOnly: true });
  try { inspectDatabase(db); validateStoredJson(db); } finally { db.close(); }
  return manifest;
}
export async function restoreBackup(backup: string, destination: string): Promise<void> {
  await verifyBackup(backup); destination = await freshDestination(destination, [backup]);
  const directory = await mkdtemp(join(dirname(destination), '.lobuddy-restore-'));
  try {
    const stage = join(directory, 'snapshot'); await copyTree(backup, stage); await verifyBackup(stage);
    await freshDestination(destination, [backup]); await rename(stage, destination);
  } finally { await rm(directory, { recursive: true, force: true }); }
}
export async function importBackup(backup: string, destination: string,
  checkpoint: (step: string) => void = () => {}): Promise<{ imported: boolean; data_dir: string; workspace: string }> {
  const manifest = await verifyBackup(backup);
  const hash = createHash('sha256').update(await readPrivate(join(backup, 'manifest.json'))).digest('hex');
  destination = resolve(destination);
  await mkdir(dirname(destination), { recursive: true, mode: 0o700 });
  destination = join(await realpath(dirname(destination)), basename(destination));
  const result = { data_dir: join(destination, 'data'), workspace: join(destination, 'workspace') };
  if (await exists(destination)) {
    const marker = ImportMarkerSchema.parse(JSON.parse((await readPrivate(join(destination, 'import.json'))).toString()));
    if (marker.backup_id !== manifest.identity || marker.manifest_sha256 !== hash) throw new StorageError('目标已有其他资料，不进行合并');
    const db = new DatabaseSync(join(result.data_dir, 'lobuddy.db'), { readOnly: true });
    try {
      if (![3, 4, STORAGE_VERSION].includes(inspectDatabase(db).version) || !db.prepare('SELECT 1 FROM ts_import WHERE identity=? AND manifest_sha256=?').get(manifest.identity, hash)) throw new StorageError('导入登记与资料不匹配');
    } finally { db.close(); }
    return { imported: false, ...result };
  }
  destination = await freshDestination(destination, [backup]);
  // Offline archives remain restorable on another machine; a reachable old source must be stopped.
  if (await exists(manifest.source_data)) await requireStopped(manifest.source_data);
  const directory = await mkdtemp(join(dirname(destination), '.lobuddy-import-'));
  try {
    const stage = join(directory, 'imported');
    await copyTree(join(backup, 'data'), join(stage, 'data')); await copyTree(join(backup, 'workspace'), join(stage, 'workspace'));
    for (const [name, expected] of Object.entries(manifest.files)) {
      if (await hashFile(relativeChild(stage, name)) !== expected) throw new StorageError('复制期间备份内容发生变化');
    }
    const store = new Store(join(stage, 'data/lobuddy.db'), { importing: true });
    try {
      const before = inspectDatabase(store.connection).counts;
      checkpoint('opened');
      await relocateReferences(store, manifest, stage, destination);
      store.transaction(() => {
        recoverImportedWork(store);
        store.run('INSERT INTO ts_import VALUES(?,?,?)', manifest.identity, hash, new Date().toISOString());
        checkpoint('before-commit');
      });
      validateStoredJson(store.connection);
      if (JSON.stringify(before) !== JSON.stringify(inspectDatabase(store.connection).counts)) throw new StorageError('导入改变了历史实体数量');
      await atomicPrivateWrite(join(stage, 'import.json'), Buffer.from(JSON.stringify({ backup_id: manifest.identity,
        manifest_sha256: hash, storage_version: STORAGE_VERSION })));
    } finally { store.close(); }
    checkpoint('before-publish');
    if (await exists(manifest.source_data)) await requireStopped(manifest.source_data);
    await freshDestination(destination, [backup]); await rename(stage, destination);
    return { imported: true, ...result };
  } finally { await rm(directory, { recursive: true, force: true }); }
}
