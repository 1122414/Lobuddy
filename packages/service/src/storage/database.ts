import { DatabaseSync, backup, type SQLInputValue } from 'node:sqlite';
import { createHash, randomUUID } from 'node:crypto';
import { chmodSync, closeSync, existsSync, lstatSync, mkdirSync, openSync, constants } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { LEGACY_SCHEMA_SQL, BUSINESS_TABLES } from './schema.js';
import { REQUIRED_COLUMNS } from './schema-columns.js';

export const STORAGE_VERSION = 5;
const LEGACY_ADDITIONS: Record<string, Record<string, string>> = {
  pet_state: { personality_json: 'TEXT' }, chat_message: { image_path: 'TEXT' },
  memory_item: { priority: 'INTEGER NOT NULL DEFAULT 50' },
  skill_record: { content: "TEXT NOT NULL DEFAULT ''" }, skill_candidate: { metadata: "TEXT NOT NULL DEFAULT '{}'" },
  project_session: { revision: 'INTEGER NOT NULL DEFAULT 0' },
};
const MIGRATIONS = [{ id: '001-ts-storage', sql: `
CREATE TABLE ts_migration(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL);
CREATE TABLE ts_import(identity TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE ts_recovery(kind TEXT NOT NULL, entity_id TEXT NOT NULL, reason TEXT NOT NULL,
 acknowledged INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(kind, entity_id));
` }, { id: '002-companion-handoff', sql: `
CREATE TABLE companion_handoff(notice_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
 message_id TEXT NOT NULL, source_id TEXT NOT NULL, revision TEXT NOT NULL, project_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','revoking','revoked')), accepted_at REAL NOT NULL,
 FOREIGN KEY(session_id) REFERENCES chat_session(id) ON DELETE CASCADE);
CREATE INDEX companion_handoff_session ON companion_handoff(session_id,accepted_at);
CREATE TABLE companion_context_use(turn_id TEXT NOT NULL, notice_id TEXT NOT NULL,
 PRIMARY KEY(turn_id,notice_id), FOREIGN KEY(notice_id) REFERENCES companion_handoff(notice_id) ON DELETE CASCADE);
` }, { id: '003-continuous-care', sql: `
CREATE TABLE companion_care(id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE companion_delivery(notice_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE companion_care_request(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, care_id TEXT NOT NULL);
` }] as const;
const migrationVersion = (id: string) => Number(id.slice(0,3)) + 2;
export class StorageError extends Error {}

export function ensurePrivateFile(path: string, create: boolean): void {
  if (!existsSync(path) && !create) throw new StorageError('数据库不存在，未创建替代数据库');
  const fd = openSync(path, constants.O_RDWR | constants.O_NOFOLLOW | (create ? constants.O_CREAT | constants.O_EXCL : 0), 0o600);
  closeSync(fd);
  if (!lstatSync(path).isFile()) throw new StorageError('数据库路径必须是普通文件');
  chmodSync(path, 0o600);
}

// Only call for a newly created, unpublished snapshot, never the live database or an existing archive.
export function sealSnapshot(path: string): number {
  const copied = new DatabaseSync(path);
  try {
    copied.exec('PRAGMA journal_mode=DELETE');
    return inspectDatabase(copied).version;
  } finally { copied.close(); }
}

// A separate rollback-journal database keeps execution ownership without locking business reads.
export class ExecutionLease {
  private connection?: DatabaseSync;
  constructor(directory: string) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const path = join(directory, 'execution.lock.sqlite');
    try {
      ensurePrivateFile(path, !existsSync(path));
      const connection = new DatabaseSync(path, { timeout: 0 });
      this.connection = connection;
      connection.exec('PRAGMA journal_mode=DELETE; BEGIN EXCLUSIVE; CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY);');
    } catch {
      this.close(); throw new StorageError('该资料已有执行进程，无法取得独占执行权');
    }
  }
  close(): void { this.connection?.close(); this.connection = undefined; }
}

export function inspectDatabase(db: DatabaseSync): { version: number; counts: Record<string, number> } {
  const integrity = db.prepare('PRAGMA integrity_check').all();
  if (integrity.length !== 1 || Object.values(integrity[0]!)[0] !== 'ok') throw new StorageError('数据库完整性校验失败');
  if (db.prepare('PRAGMA foreign_key_check').all().length) throw new StorageError('数据库存在失效关联');
  const version = Number(db.prepare('PRAGMA user_version').get()!.user_version);
  if (![0, 1, 2, 3, 4, STORAGE_VERSION].includes(version)) throw new StorageError('未知数据库版本，未修改资料');
  const tables = new Set(db.prepare("SELECT name FROM sqlite_schema WHERE type='table'").all().map(row => String(row.name)));
  if (!tables.has('pet_state') || (version >= 2 && !tables.has('chat_session'))) throw new StorageError('不是可识别的 Lobuddy 资料库');
  if (db.prepare("SELECT name FROM sqlite_schema WHERE type IN ('trigger','view')").all().length) throw new StorageError('资料库包含未知触发器或视图');
  for (const [table, columns] of Object.entries(REQUIRED_COLUMNS)) {
    if (!tables.has(table)) continue;
    const present = new Set(db.prepare(`PRAGMA table_info("${table}")`).all().map(row => String(row.name)));
    if (columns.some(column => !present.has(column) && (version >= 3 || !LEGACY_ADDITIONS[table]?.[column]))) throw new StorageError(`旧库缺少所需字段：${table}`);
  }
  if (version >= 3) verifyMigrations(db, version);
  if (version >= 4 && ['companion_handoff','companion_context_use'].some(table => !tables.has(table))) throw new StorageError('接话存储结构缺失');
  if (version >= 5 && ['companion_care','companion_delivery','companion_care_request'].some(table => !tables.has(table))) throw new StorageError('关心存储结构缺失');
  const counts: Record<string, number> = {};
  for (const table of BUSINESS_TABLES) {
    if (!tables.has(table)) continue;
    // Identifiers are a compiled allowlist, never user input.
    counts[table] = Number(db.prepare(`SELECT count(*) AS count FROM "${table}"`).get()!.count);
    // Reading each integer prevents silent truncation of legacy 64-bit data.
    for (const row of db.prepare(`SELECT * FROM "${table}"`).iterate()) {
      for (const value of Object.values(row)) {
        if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) {
          throw new StorageError('旧数据包含超出 JavaScript 安全整数范围的值');
        }
      }
    }
  }
  return { version, counts };
}

export class Store {
  readonly created: boolean;
  readonly connection!: DatabaseSync;
  private readonly lease: ExecutionLease;
  private transactionActive = false;
  private closed = false;
  constructor(readonly path: string, options: { create?: boolean; importing?: boolean } = {}) {
    this.created = Boolean(options.create && !options.importing);
    path = resolve(path);
    this.path = path;
    if (options.create && existsSync(path)) throw new StorageError('目标已存在，不覆盖已有资料');
    if (!options.create && !existsSync(path)) throw new StorageError('数据库不存在，未创建替代数据库');
    mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    this.lease = new ExecutionLease(dirname(path));
    try {
      ensurePrivateFile(path, Boolean(options.create));
      this.connection = new DatabaseSync(path, { timeout: 3000, enableForeignKeyConstraints: true, allowExtension: false });
      this.connection.exec('PRAGMA trusted_schema=OFF;');
      if (options.create) {
        this.transaction(() => { this.connection.exec(LEGACY_SCHEMA_SQL); this.connection.exec('PRAGMA user_version=2'); });
      }
      const current = inspectDatabase(this.connection);
      if (current.version < 3 && !options.create && !options.importing) {
        throw new StorageError('旧资料须先备份并导入新目录，不允许原地升级');
      }
      if (current.version >= 3 && current.version < STORAGE_VERSION && !options.importing) {
        // VACUUM reads committed WAL content, unlike copying the main file. Keep the snapshot on failure.
        const snapshot = join(dirname(path), `pre-v${STORAGE_VERSION}-${randomUUID()}.sqlite`);
        ensurePrivateFile(snapshot, true);
        this.connection.prepare('VACUUM INTO ?').run(snapshot);
        if (sealSnapshot(snapshot) !== current.version) throw new StorageError('升级前备份版本错误');
      }
      if (current.version < STORAGE_VERSION) this.migrate(current.version);
      verifyMigrations(this.connection);
      this.connection.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;');
    } catch (error) {
      this.connection?.close(); this.lease.close(); throw error;
    }
  }
  private migrate(version: number): void {
    this.transaction(() => {
      const present = new Set(this.connection.prepare("SELECT name FROM sqlite_schema WHERE type='table'").all().map(row => String(row.name)));
      // Only the additive migrations already supported by the old application are accepted.
      for (const [table, columns] of Object.entries(LEGACY_ADDITIONS)) {
        if (!present.has(table)) continue;
        const existing = new Set(this.connection.prepare(`PRAGMA table_info("${table}")`).all().map(row => String(row.name)));
        for (const [column, definition] of Object.entries(columns)) if (!existing.has(column)) {
          this.connection.exec(`ALTER TABLE "${table}" ADD COLUMN "${column}" ${definition}`);
        }
      }
      this.connection.exec(LEGACY_SCHEMA_SQL.replace(/CREATE (VIRTUAL TABLE|TABLE|INDEX) /g, 'CREATE $1 IF NOT EXISTS '));
      for (const migration of MIGRATIONS) {
        if (migrationVersion(migration.id) <= version) continue;
        this.connection.exec(migration.sql);
        this.connection.prepare('INSERT INTO ts_migration VALUES(?,?,?)').run(migration.id,
          migrationHash(migration.sql), new Date().toISOString());
      }
      this.connection.exec(`PRAGMA user_version=${STORAGE_VERSION}`);
    });
  }
  transaction<T>(operation: () => T): T {
    if (this.transactionActive) throw new StorageError('禁止隐式嵌套事务');
    this.transactionActive = true;
    try {
      this.connection.exec('BEGIN IMMEDIATE');
      try {
        const result = operation();
        if (result && typeof (result as { then?: unknown }).then === 'function') throw new StorageError('事务不能跨异步边界');
        this.connection.exec('COMMIT'); return result;
      } catch (error) { this.connection.exec('ROLLBACK'); throw error; }
    } finally { this.transactionActive = false; }
  }
  run(sql: string, ...params: SQLInputValue[]) { return this.connection.prepare(sql).run(...params); }
  async backup(path: string): Promise<void> {
    ensurePrivateFile(path, true);
    await backup(this.connection, path);
    sealSnapshot(path);
  }
  close(): void {
    if (this.closed) return;
    this.closed = true;
    try { this.connection.close(); } finally { this.lease.close(); }
  }
}

function verifyMigrations(db: DatabaseSync, version = STORAGE_VERSION): void {
  const expected = MIGRATIONS.filter(migration => migrationVersion(migration.id) <= version);
  const rows = db.prepare('SELECT id,sha256 FROM ts_migration ORDER BY id').all();
  if (rows.length !== expected.length || rows.some((row, index) => row.id !== expected[index]!.id ||
    row.sha256 !== migrationHash(expected[index]!.sql))) {
    throw new StorageError('迁移登记未知或校验值不一致');
  }
}

function migrationHash(sql: string): string {
  return createHash('sha256').update(JSON.stringify({ sql, legacy: LEGACY_SCHEMA_SQL, additive: LEGACY_ADDITIONS })).digest('hex');
}
