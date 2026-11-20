// Exercise the real installed startup migration, not just the storage helper.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, readFileSync, writeFileSync, cpSync, readdirSync, realpathSync, existsSync, rmSync } = require('node:fs');
const { DatabaseSync } = require('node:sqlite');
const { createHash } = require('node:crypto');
const { join, resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const { tmpdir } = require('node:os');

const root = resolve(__dirname, '../..');
const hash = path => createHash('sha256').update(readFileSync(path)).digest('hex');
(async () => {
  const reportPath = resolve(root, process.env.LOBUDDY_MIGRATION_REPORT || 'reports/2026-10-21_t10_package_migration.json');
  assert.ok(!existsSync(reportPath), 'Use a fresh report path to preserve prior evidence');
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-package-migration-'));
  const report = { status: 'running', scope: 'isolated synthetic legacy data; no user data or credentials', checks: [] };
  let app;
  try {
    const source = readFileSync(join(root, 'desktop/release/latest.txt'), 'utf8').trim();
    const target = join(temporary, 'Relocated Lobuddy.app');
    cpSync(source, target, { recursive: true, verbatimSymlinks: true });
    const bundled = join(target, 'Contents/Resources/app');
    report.bundle_manifest_sha256 = hash(join(bundled, 'assets/bundle-manifest.json'));
    const { LEGACY_SCHEMA_SQL } = await import(pathToFileURL(join(bundled, 'packages/service/dist/storage/schema.js')).href);
    const { restoreBackup, verifyBackup } = await import(pathToFileURL(join(bundled, 'packages/service/dist/storage/backup.js')).href);
    const profile = join(temporary, 'profile'), legacy = join(profile, 'service');
    mkdirSync(join(legacy, 'workspace'), { recursive: true });
    const original = join(legacy, 'lobuddy.db');
    const db = new DatabaseSync(original);
    db.exec(LEGACY_SCHEMA_SQL + '\nPRAGMA user_version=2;');
    db.prepare('INSERT INTO pet_state(id,created_at,updated_at) VALUES(?,?,?)')
      .run('pet-migration', '2026-10-01T12:00:00', '2026-10-01T12:00:00');
    db.prepare('INSERT INTO chat_session VALUES(?,?,?,?,?)')
      .run('session-migration', 'pet-migration', '升级前对话', '2026-10-01T12:00:00', '2026-10-01T12:00:00');
    db.prepare('INSERT INTO chat_message VALUES(?,?,?,?,?,?)')
      .run('message-migration', 'session-migration', 'user', '这是合成迁移记录', null, '2026-10-01T12:00:00');
    db.close();
    const originalHash = hash(original);
    const launch = async () => {
      app = await electron.launch({ executablePath: join(target, 'Contents/MacOS/Lobuddy'),
        args: [`--user-data-dir=${profile}`], cwd: temporary, timeout: 30000,
        env: { HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, PATH: '/usr/bin:/bin',
          LLM_API_KEY: 'synthetic-unused', LLM_MULTIMODAL_API_KEY: 'synthetic-unused',
          FISH_API_KEY: 'synthetic-unused', TYPESAFE_API_KEY: 'synthetic-unused' } });
      const page = await app.firstWindow();
      await page.getByText('服务已连接', { exact: true }).waitFor();
      report.checkpoint = 'isolated_profile';
      assert.equal(realpathSync(await app.evaluate(({ app }) => app.getPath('userData'))), realpathSync(profile));
      const sessions = await page.evaluate(() => window.lobuddy.request('session.list', {}, crypto.randomUUID()));
      report.checkpoint = 'session_imported';
      assert.ok(sessions.some(session => session.id === 'session-migration'));
      await app.close(); app = undefined;
    };
    report.phase = 'first_startup';
    await launch();
    report.checkpoint = 'source_unchanged';
    assert.equal(hash(original), originalHash);
    const backupRoot = join(profile, 'upgrade-backups');
    report.checkpoint = 'one_backup';
    assert.equal(readdirSync(backupRoot).length, 1);
    report.checks.push('installed_startup_import_preserves_original_and_session_id');
    report.phase = 'restart';
    await launch();
    assert.equal(readdirSync(backupRoot).length, 1);
    const migrated = new DatabaseSync(join(profile, 'typescript/data/lobuddy.db'), { readOnly: true });
    try {
      assert.equal(migrated.prepare('PRAGMA user_version').get().user_version, 3);
      assert.equal(migrated.prepare('SELECT COUNT(*) n FROM chat_message WHERE id=?').get('message-migration').n, 1);
      assert.equal(migrated.prepare('SELECT pet_id FROM chat_session WHERE id=?').get('session-migration').pet_id, 'pet-migration');
    } finally { migrated.close(); }
    assert.equal(hash(original), originalHash);
    report.checks.push('restart_keeps_one_backup_and_original_message_relationship');
    report.phase = 'rollback';
    const backup = join(backupRoot, readdirSync(backupRoot)[0]);
    await verifyBackup(backup);
    await restoreBackup(backup, join(temporary, 'restored'));
    assert.equal(hash(join(temporary, 'restored/data/lobuddy.db')), hash(join(backup, 'data/lobuddy.db')));
    const restored = new DatabaseSync(join(temporary, 'restored/data/lobuddy.db'), { readOnly: true });
    try { assert.equal(restored.prepare('PRAGMA user_version').get().user_version, 2); }
    finally { restored.close(); }
    report.checks.push('bundled_restore_recovers_checksum_verified_legacy_version');
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error_category = error.name;
    process.exitCode = 1;
  } finally {
    try {
      if (app) await app.close();
      report.ended_at = new Date().toISOString();
      writeFileSync(reportPath, JSON.stringify(report, null, 2), { flag: 'wx' });
    } finally { rmSync(temporary, { recursive: true, force: true }); }
  }
  console.log(JSON.stringify(report));
})().catch(() => { console.error('Isolated package migration setup or cleanup failed.'); process.exitCode = 1; });
