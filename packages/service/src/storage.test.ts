import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, rm, symlink, lstat, realpath, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { LEGACY_SCHEMA_SQL } from './storage/schema.js';
import { Store, inspectDatabase, ExecutionLease, STORAGE_VERSION } from './storage/database.js';
import { createBackup, importBackup, restoreBackup, verifyBackup } from './storage/backup.js';
import { hashFile } from './storage/files.js';
import { DelegationViewSchema, TurnStateSchema } from '@lobuddy/contracts';

async function fixture() {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'lobuddy-storage-')));
  const data = join(root, 'old/data'), workspace = join(root, 'old/workspace');
  await mkdir(data, { recursive: true }); await mkdir(join(workspace, 'skills/example'), { recursive: true });
  const path = join(data, 'lobuddy.db');
  const db = new DatabaseSync(path);
  db.exec(LEGACY_SCHEMA_SQL + '\nPRAGMA user_version=2;');
  db.prepare('INSERT INTO pet_state(id,created_at,updated_at) VALUES(?,?,?)').run('pet-old', '2026-10-01T12:00:00', '2026-10-01T12:00:00');
  db.prepare('INSERT INTO chat_session VALUES(?,?,?,?,?)').run('session-old', 'pet-old', '旧对话', '2026-10-01T12:00:00', '2026-10-01T12:00:00');
  db.prepare('INSERT INTO chat_message VALUES(?,?,?,?,?,?)').run('message-old', 'session-old', 'user', '喜欢少说一点', null, '2026-10-01T12:00:00');
  const state = TurnStateSchema.parse({ turn_id: 'turn-old', task_id: 'task-old', session_id: 'session-old', engine_id: 'engine-old', lane: 'foreground', status: 'running', input_text: '测试' });
  const request = JSON.stringify({ session_id: 'session-old', text: '测试' });
  db.prepare('INSERT INTO service_turn VALUES(?,?,?,?)').run(state.turn_id, 'request-old', request, JSON.stringify(state));
  db.prepare('INSERT INTO engine_session VALUES(?,?,?,1)').run('session-old', 'foreground', 'engine-old');
  const delegation = DelegationViewSchema.parse({ id: 'delegation-old', revision: 1, status: 'waiting_user', created_at: 1, updated_at: 1,
    authorized_at: 1, spec: { goal: '提醒休息', criteria: ['通知按规则投递（不代表已读）'], wait: { kind: 'user' } } });
  db.prepare('INSERT INTO delegation VALUES(?,?)').run(delegation.id, JSON.stringify(delegation));
  db.prepare('INSERT INTO delegation_revision VALUES(?,?,?)').run(delegation.id, 1, JSON.stringify(delegation));
  db.prepare('INSERT INTO delegation_request VALUES(?,?,?)').run('request-delegation-old', 'exact-python-fingerprint', JSON.stringify(delegation));
  db.prepare('INSERT INTO learning_budget VALUES(?,?,?,?)').run('2026-10-21', 29, 59999, 7999);
  db.prepare('INSERT INTO skill_record(id,name,path,description,created_at,updated_at,content) VALUES(?,?,?,?,?,?,?)')
    .run('skill-old', 'example', join(workspace, 'skills/example/SKILL.md'), '历史技能', '2026-10-01T12:00:00', '2026-10-01T12:00:00', '# retained');
  db.close();
  await writeFile(join(workspace, 'skills/example/SKILL.md'), '# retained');
  return { root, data, workspace, path, clean: () => rm(root, { recursive: true, force: true }) };
}

async function versionThree() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-v3-upgrade-')), path = join(root, 'data/lobuddy.db');
  const store = new Store(path, { create: true });
  assert.equal(store.connection.prepare("SELECT sha256 FROM ts_migration WHERE id='001-ts-storage'").get()!.sha256,
    'd5aba2f67736c8f6cb3c1f997f7b2ec947130fa4a1aefda01b3d1e5b2f899469', 'original TS migration fingerprint');
  store.connection.exec("DROP TABLE companion_context_use; DROP TABLE companion_handoff; DELETE FROM ts_migration WHERE id='002-companion-handoff'; PRAGMA user_version=3;");
  store.run("INSERT INTO chat_session VALUES('retained','default','保留历史','2026-10-01T12:00:00','2026-10-01T12:00:00')");
  store.close(); return { root, path };
}
test('verified v3 upgrades atomically with a private usable snapshot and preserves migration identity', async () => {
  const f = await versionThree();
  try {
    const store = new Store(f.path);
    assert.equal(inspectDatabase(store.connection).version, 4);
    assert.equal(store.connection.prepare('SELECT id FROM chat_session').get()!.id, 'retained');
    store.close();
    const snapshots = (await readdir(dirname(f.path))).filter(name => name.startsWith('pre-v4-'));
    assert.equal(snapshots.length, 1);
    const backup = join(dirname(f.path), snapshots[0]!);
    assert.equal((await lstat(backup)).mode & 0o777, 0o600);
    const old = new DatabaseSync(backup, { readOnly: true });
    try { assert.equal(inspectDatabase(old).version, 3); assert.equal(old.prepare('SELECT id FROM chat_session').get()!.id, 'retained'); }
    finally { old.close(); }
    new Store(f.path).close();
    assert.equal((await readdir(dirname(f.path))).filter(name => name.startsWith('pre-v4-')).length, 1, 'restart does not remigrate');
  } finally { await rm(f.root, { recursive: true, force: true }); }
});
test('a failed v3 additive migration rolls back and a forged migration is rejected before backup', async () => {
  const f = await versionThree();
  try {
    const db = new DatabaseSync(f.path);
    db.exec('CREATE TABLE companion_context_use(turn_id TEXT,notice_id TEXT)'); db.close();
    assert.throws(() => new Store(f.path), /already exists/);
    const current = new DatabaseSync(f.path);
    assert.equal(inspectDatabase(current).version, 3);
    assert.equal(current.prepare('SELECT count(*) n FROM ts_migration').get()!.n, 1);
    assert.equal(current.prepare("SELECT name FROM sqlite_schema WHERE name='companion_handoff'").get(), undefined);
    assert.equal(current.prepare('SELECT id FROM chat_session').get()!.id, 'retained');
    current.exec("DROP TABLE companion_context_use; UPDATE ts_migration SET sha256='forged'"); current.close();
    const count = (await readdir(dirname(f.path))).length;
    assert.throws(() => new Store(f.path), /校验/);
    assert.equal((await readdir(dirname(f.path))).length, count);
  } finally { await rm(f.root, { recursive: true, force: true }); }
});
test('v3 still requires every frozen column before attempting an additive upgrade', async () => {
  const f = await versionThree();
  try {
    const db = new DatabaseSync(f.path); db.exec('ALTER TABLE memory_item DROP COLUMN priority'); db.close();
    assert.throws(() => new Store(f.path), /缺少所需字段/);
    assert.equal((await readdir(dirname(f.path))).filter(name => name.startsWith('pre-v4-')).length, 0);
  } finally { await rm(f.root, { recursive: true, force: true }); }
});

test('v4 handoff provenance survives backup and import without duplicating a conversation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-handoff-import-'));
  try {
    const data = join(root,'old/data'), workspace = join(root,'old/workspace'); await mkdir(workspace,{ recursive: true });
    const store = new Store(join(data,'lobuddy.db'), { create: true });
    store.run("INSERT INTO chat_session VALUES('s','default','接话','2026-10-01T12:00:00','2026-10-01T12:00:00')");
    store.run("INSERT INTO chat_message VALUES('m','s','assistant','我在这里',NULL,'2026-10-01T12:00:00')");
    store.run("INSERT INTO companion_handoff VALUES('n','s','m','','','','active',1)");
    store.run("INSERT INTO companion_context_use VALUES('t','n')"); store.close();
    const snapshot = join(root,'backup'); await createBackup(data,workspace,snapshot);
    const imported = await importBackup(snapshot,join(root,'new'));
    const reopened = new Store(join(imported.data_dir,'lobuddy.db'));
    assert.equal(reopened.connection.prepare('SELECT notice_id FROM companion_handoff').get()!.notice_id,'n');
    assert.equal(reopened.connection.prepare('SELECT turn_id FROM companion_context_use').get()!.turn_id,'t');
    assert.equal(reopened.connection.prepare('SELECT count(*) n FROM chat_message').get()!.n,1); reopened.close();
    assert.equal((await importBackup(snapshot,join(root,'new'))).imported,false);
  } finally { await rm(root,{ recursive: true,force: true }); }
});
test('old IDs, source data, fingerprints, budgets and backups survive an idempotent isolated import', async () => {
  const f = await fixture();
  try {
    const originalHash = await hashFile(f.path);
    const snapshot = join(f.root, 'backup');
    await createBackup(f.data, f.workspace, snapshot);
    const target = join(f.root, 'new');
    assert.equal((await importBackup(snapshot, target)).imported, true);
    assert.equal((await importBackup(snapshot, target)).imported, false);
    assert.equal(await hashFile(f.path), originalHash);
    const store = new Store(join(target, 'data/lobuddy.db'));
    try {
      assert.equal(inspectDatabase(store.connection).version, STORAGE_VERSION);
      assert.equal(store.connection.prepare('SELECT id FROM pet_state').get()!.id, 'pet-old');
      assert.equal(store.connection.prepare('SELECT fingerprint FROM delegation_request').get()!.fingerprint, 'exact-python-fingerprint');
      assert.equal(store.connection.prepare('SELECT calls FROM learning_budget').get()!.calls, 29);
      assert.equal(JSON.parse(String(store.connection.prepare('SELECT state_json FROM service_turn').get()!.state_json)).status, 'interrupted');
      assert.equal(JSON.parse(String(store.connection.prepare('SELECT body FROM delegation').get()!.body)).status, 'needs_review');
      assert.equal(JSON.parse(String(store.connection.prepare('SELECT body FROM delegation_revision').get()!.body)).status, 'waiting_user');
      assert.equal(store.connection.prepare('SELECT content FROM skill_record').get()!.content, '# retained');
      assert.ok(String(store.connection.prepare('SELECT path FROM skill_record').get()!.path).startsWith(target));
      assert.equal(store.connection.prepare('SELECT count(*) n FROM ts_migration').get()!.n, 2);
    } finally { store.close(); }
    await restoreBackup(snapshot, join(f.root, 'restored'));
    assert.equal(await hashFile(join(f.root, 'restored/data/lobuddy.db')), await hashFile(join(snapshot, 'data/lobuddy.db')));
    assert.equal((await lstat(join(target, 'data/lobuddy.db'))).mode & 0o777, 0o600);
  } finally { await f.clean(); }
});
test('interrupted import never publishes partial data and a retry can complete', async () => {
  const f = await fixture();
  try {
    const backup = join(f.root, 'backup'); await createBackup(f.data, f.workspace, backup);
    for (const point of ['opened', 'before-commit', 'before-publish']) {
      const target = join(f.root, point);
      await assert.rejects(importBackup(backup, target, step => { if (step === point) throw new Error('fault injection'); }), /fault injection/);
      await assert.rejects(lstat(target), { code: 'ENOENT' });
      assert.equal((await importBackup(backup, target)).imported, true);
    }
  } finally { await f.clean(); }
});
test('corrupt, newer, unsafe integers, edited migrations and in-place legacy writes are rejected', async () => {
  const f = await fixture();
  try {
    assert.throws(() => new Store(f.path), /原地/);
    const corrupt = join(f.root, 'corrupt.db'); await writeFile(corrupt, 'corrupt-synthetic');
    await assert.rejects(async () => new Store(corrupt));
    assert.equal((await readFile(corrupt)).toString(), 'corrupt-synthetic');
    const db = new DatabaseSync(f.path);
    db.exec('PRAGMA user_version=999'); assert.throws(() => inspectDatabase(db), /未知/);
    db.exec('PRAGMA user_version=2'); db.prepare('UPDATE pet_state SET exp=?').run(9007199254740993n);
    assert.throws(() => inspectDatabase(db)); db.close();
    const own = new Store(join(f.root, 'new/lobuddy.db'), { create: true });
    own.run("UPDATE ts_migration SET sha256='tampered'"); own.close();
    assert.throws(() => new Store(join(f.root, 'new/lobuddy.db')), /校验/);
  } finally { await f.clean(); }
});
test('backup rejects symlinks, tampering, extra files and path traversal', async () => {
  const f = await fixture();
  try {
    await symlink('/etc/hosts', join(f.data, 'escape'));
    await assert.rejects(createBackup(f.data, f.workspace, join(f.root, 'bad')), /符号链接/);
    await rm(join(f.data, 'escape'));
    const snapshot = join(f.root, 'good'); await createBackup(f.data, f.workspace, snapshot);
    const manifest = JSON.parse((await readFile(join(snapshot, 'manifest.json'))).toString());
    manifest.files['../escape'] = 'a'.repeat(64);
    await writeFile(join(snapshot, 'manifest.json'), JSON.stringify(manifest));
    await assert.rejects(verifyBackup(snapshot));
    delete manifest.files['../escape']; await writeFile(join(snapshot, 'manifest.json'), JSON.stringify(manifest));
    await writeFile(join(snapshot, 'data/unlisted'), 'extra'); await assert.rejects(verifyBackup(snapshot), /清单/);
    await rm(join(snapshot, 'data/unlisted'));
    await writeFile(join(snapshot, 'workspace/skills/example/SKILL.md'), 'changed'); await assert.rejects(verifyBackup(snapshot), /校验/);
  } finally { await f.clean(); }
});
test('SQLite execution ownership excludes another process and is released by process death', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'lobuddy-lease-'));
  let child: ReturnType<typeof spawn> | undefined;
  try {
    const code = `import {ExecutionLease} from ${JSON.stringify(new URL('./storage/database.js', import.meta.url).href)}; const lease=new ExecutionLease(process.argv[1]); process.stdout.write('ready\\n'); setInterval(()=>{},1000);`;
    child = spawn(process.execPath, ['--input-type=module', '-e', code, directory], { stdio: ['ignore', 'pipe', 'pipe'] });
    await once(child.stdout!, 'data'); assert.throws(() => new ExecutionLease(directory), /独占/);
    const exit = once(child, 'exit'); child.kill('SIGKILL'); await exit;
    const lockPath = join(directory, 'execution.lock.sqlite'), inode = (await lstat(lockPath)).ino;
    const lease = new ExecutionLease(directory); lease.close(); assert.equal((await lstat(lockPath)).ino, inode);
    const victim = join(directory, 'victim'); await writeFile(victim, 'unchanged');
    await rm(lockPath); await symlink(victim, lockPath);
    assert.throws(() => new ExecutionLease(directory), /独占/);
    assert.equal(await readFile(victim, 'utf8'), 'unchanged');
  } finally { child?.kill(); await rm(directory, { recursive: true, force: true }); }
});
test('online backup includes committed WAL rows and transactions roll back atomically', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'lobuddy-wal-'));
  const store = new Store(join(directory, 'lobuddy.db'), { create: true });
  try {
    store.run("INSERT INTO app_settings VALUES('retained','1','now')");
    assert.throws(() => store.transaction(() => { store.run("INSERT INTO app_settings VALUES('rolled-back','1','now')"); throw new Error('injected'); }));
    assert.equal(store.connection.prepare("SELECT count(*) n FROM app_settings WHERE key='rolled-back'").get()!.n, 0);
    const path = join(directory, 'copy.db'); await store.backup(path);
    const copy = new DatabaseSync(path, { readOnly: true });
    try { assert.equal(copy.prepare('SELECT value FROM app_settings').get()!.value, '1'); } finally { copy.close(); }
  } finally { store.close(); await rm(directory, { recursive: true, force: true }); }
});
test('stopped-runtime check vetoes a held legacy lock without changing its database', async () => {
  const f = await fixture();
  const { open } = await import('node:fs/promises');
  const handle = await open(join(f.data, 'service.lock'), 'w');
  try {
    const before = await hashFile(f.path);
    await assert.rejects(createBackup(f.data, f.workspace, join(f.root, 'blocked')), /使用|停机/);
    assert.equal(await hashFile(f.path), before);
    await handle.close();
    await createBackup(f.data, f.workspace, join(f.root, 'stopped'));
  } finally { await handle.close(); await f.clean(); }
});

test('Node service keeps sessions and settings across a real worker restart', async () => {
  const { Worker } = await import('node:worker_threads');
  const { RpcClient } = await import('./rpc-client.js');
  const { portTransport } = await import('./transport.js');
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-storage-worker-'));
  let sessionId = '';
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const worker = new Worker(new URL('./node-host.js', import.meta.url), { workerData: { kind: 'connect', storage: {
        data: root, workspace: join(root, 'workspace'), logs: join(root, 'logs'), create: attempt === 0 } } });
      const client = new RpcClient(portTransport({
        postMessage: value => worker.postMessage(value), start: () => {}, close: () => {},
        on: (event, listener) => worker.on(event === 'close' ? 'exit' : event, listener),
        off: (event, listener) => worker.off(event === 'close' ? 'exit' : event, listener),
      }, 'node'));
      try {
        await client.start();
        if (attempt === 0) {
          const session = await client.request('session.create', { title: '持久会话' }); sessionId = session.id;
          await client.request('settings.patch', { values: { pet_name: '浊蒂', focus_default_minutes: 30 } });
        } else {
          const sessions = await client.request('session.list', {}); assert.equal(sessions[0]!.id, sessionId);
          const settings = await client.request('settings.get', {}); assert.equal(settings.values.pet_name, '浊蒂');
          assert.equal(settings.values.focus_default_minutes, 30);
        }
        const exited = once(worker, 'exit'); client.close(); assert.deepEqual(await exited, [0]);
      } finally { client.close(); await worker.terminate(); }
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('historical partial schema uses only known additive migrations and never alters the original', async () => {
  const f = await fixture();
  try {
    const db = new DatabaseSync(f.path);
    db.exec('ALTER TABLE skill_record DROP COLUMN content; ALTER TABLE memory_item DROP COLUMN priority; PRAGMA user_version=0;');
    db.close();
    const before = await hashFile(f.path), snapshot = join(f.root, 'legacy-backup');
    await createBackup(f.data, f.workspace, snapshot);
    await importBackup(snapshot, join(f.root, 'latest'));
    const imported = new Store(join(f.root, 'latest/data/lobuddy.db'));
    try {
      assert.equal(imported.connection.prepare('SELECT content FROM skill_record').get()!.content, '# retained');
      assert.equal(imported.connection.prepare('SELECT id FROM pet_state').get()!.id, 'pet-old');
    } finally { imported.close(); }
    assert.equal(await hashFile(f.path), before);
  } finally { await f.clean(); }
});
test('frozen records produced by the Python public service preserve knowledge, versions and sources', async () => {
  const f = await fixture();
  try {
    const contents = await readFile(new URL('../../../migration/fixtures/legacy-records.json', import.meta.url), 'utf8');
    const frozen = JSON.parse(contents.replaceAll('__OLD_WORKSPACE__', f.workspace).replaceAll('__OLD_DATA__', f.data)) as {
      tables: Record<string, Record<string, string | number | null>[]>; workspace_files: Record<string, string> };
    for (const [name, content] of Object.entries(frozen.workspace_files)) {
      assert.ok(!name.includes('..') && !name.startsWith('/'));
      const path = join(f.workspace, name); await mkdir(dirname(path), { recursive: true }); await writeFile(path, content);
    }
    const db = new DatabaseSync(f.path);
    // Replace only this test's synthetic rows; the fixture was emitted by old public methods.
    db.exec('PRAGMA foreign_keys=OFF');
    for (const table of Object.keys(frozen.tables)) {
      assert.match(table, /^[a-z_]+$/);
      db.exec(`DELETE FROM "${table}"`);
      for (const row of frozen.tables[table]!) {
        const columns = Object.keys(row); for (const column of columns) assert.match(column, /^[a-z_]+$/);
        db.prepare(`INSERT INTO "${table}"(${columns.map(name => `"${name}"`).join(',')}) VALUES(${columns.map(() => '?').join(',')})`).run(...Object.values(row));
      }
    }
    db.close();
    const snapshot = join(f.root, 'oracle-backup'), target = join(f.root, 'oracle-ts');
    await createBackup(f.data, f.workspace, snapshot); await importBackup(snapshot, target);
    const migrated = new Store(join(target, 'data/lobuddy.db'));
    try {
      for (const table of ['memory_item', 'relationship', 'relationship_revision', 'relationship_barrier',
        'personal_project', 'project_source', 'skill_version', 'workflow_version', 'project_context_use']) {
        const rows = migrated.connection.prepare(`SELECT * FROM "${table}"`).all().map(row => ({ ...row }));
        assert.deepEqual(rows, frozen.tables[table], table);
      }
    } finally { migrated.close(); }
    for (const [name, content] of Object.entries(frozen.workspace_files)) {
      assert.equal(await readFile(join(target, 'workspace', name), 'utf8'), content, name);
    }
  } finally { await f.clean(); }
});
test('persisted JSON never rounds unsafe integers inside open-ended workflow data', async () => {
  const { parseStoredJson } = await import('./storage/json.js');
  assert.throws(() => parseStoredJson('{"arguments":{"count":9007199254740993}}'), /数值/);
  assert.throws(() => parseStoredJson('{"value":1e400}'), /数值/);
  assert.deepEqual(parseStoredJson('{"value":0.8,"limit":9007199254740991}'), { value: 0.8, limit: Number.MAX_SAFE_INTEGER });
});
test('chat recency uses write time and malformed pet traits keep the legacy fallback', async () => {
  const { PetRepository } = await import('./storage/pet.js');
  const { ChatRepository } = await import('./storage/chat.js');
  const { ChatSessionSchema, ChatMessageSchema, PetPersonalitySchema } = await import('@lobuddy/contracts');
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-repository-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  try {
    const pet = new PetRepository(store), chat = new ChatRepository(store);
    pet.getOrCreate();
    store.run('UPDATE pet_state SET personality_json=?', '{invalid');
    assert.deepEqual(pet.get()!.personality, PetPersonalitySchema.parse({}));
    chat.saveSession(ChatSessionSchema.parse({ id: 'session', created_at: '2000-01-01T00:00:00', updated_at: '2000-01-01T00:00:00' }));
    chat.saveMessage(ChatMessageSchema.parse({ id: 'message', session_id: 'session', role: 'user', content: '旧消息', created_at: '2000-01-01T00:00:00' }));
    assert.notEqual(chat.getSession('session')!.updated_at, '2000-01-01T00:00:00');
    assert.equal(chat.messages('session')[0]!.created_at, '2000-01-01T00:00:00');
  } finally { store.close(); await rm(root, { recursive: true, force: true }); }
});
