// N0: isolated native lifecycle evidence. Run after npm run build.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, writeFileSync, appendFileSync, rmSync } = require('node:fs');
const { execFileSync } = require('node:child_process');
const { join, resolve, dirname } = require('node:path');
const { tmpdir } = require('node:os');
const { performance } = require('node:perf_hooks');
const { readEvents, classify, resourceVerdict, bootstrapSource } = require('./runtime-evidence.cjs');

const root = resolve(__dirname, '../..');
const duration = Number(process.env.LOBUDDY_SOAK_SECONDS || 7200);
const interval = Number(process.env.LOBUDDY_SOAK_INTERVAL || 30);
const fault = process.env.LOBUDDY_SOAK_FAULT || '';
assert.ok(Number.isFinite(duration) && duration >= 1 && duration <= 14400);
assert.ok(Number.isFinite(interval) && interval > 0 && interval <= 60);
assert.ok(['', 'quit', 'renderer', 'python', 'electron'].includes(fault));
const report = resolve(root, process.env.LOBUDDY_SOAK_REPORT || `reports/2026-10-19_n0_soak-${Date.now()}.json`);
const eventPath = report.replace(/\.json$/, '') + '.events.jsonl';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function processRows() {
  return execFileSync('ps', ['-axo', 'pid=,ppid=,rss='], { encoding: 'utf8' }).trim().split('\n')
    .map(line => line.trim().split(/\s+/).map(Number));
}
function processTree(pid) {
  const rows = processRows(); const ids = new Set([pid]); let changed = true;
  while (changed) {
    changed = false;
    for (const [child, parent] of rows) if (ids.has(parent) && !ids.has(child)) { ids.add(child); changed = true; }
  }
  return rows.filter(([id]) => ids.has(id));
}

(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-n0-'));
  mkdirSync(dirname(report), { recursive: true });
  // Refuse to replace a previous run's evidence.
  writeFileSync(eventPath, '', { flag: 'wx', mode: 0o600 });
  const start = performance.now(); let app; let page; let cleanup = false; let faultInjected = false;
  const owned = new Set();
  const state = { status: 'running', runner_pid: process.pid, started_at: new Date().toISOString(), required_seconds: duration,
    fault: fault || null, scope: 'isolated Electron/Python synthetic tasks; microphone and model learning disabled',
    tasks: 0, samples: [], events_file: eventPath.slice(root.length + 1) };
  const record = (kind, fields = {}) => appendFileSync(eventPath, JSON.stringify({ at: new Date().toISOString(), kind, cleanup, ...fields }) + '\n');
  const save = () => writeFileSync(report, JSON.stringify({ ...state, elapsed_seconds: (performance.now() - start) / 1000 }, null, 2), { mode: 0o600 });
  let terminationRequested = false;
  const signals = new Map(['SIGTERM', 'SIGINT'].map(signal => {
    const handler = () => { terminationRequested = true; record('runner-signal', { signal }); save(); };
    process.on(signal, handler); return [signal, handler];
  }));
  try {
    mkdirSync(join(temporary, 'workspace'));
    writeFileSync(join(temporary, 'workspace/note.txt'), '决定：保留来源。\n待办：验证重复运行。');
    const bootstrap = join(temporary, 'bootstrap.cjs');
    writeFileSync(bootstrap, bootstrapSource({ profile: join(temporary, 'profile'), appPath: join(root, 'desktop'),
      mainPath: join(root, 'desktop/dist-electron/desktop/electron/main.js'), eventPath }));
    app = await electron.launch({ args: [bootstrap], timeout: 30000, env: { ...process.env,
      LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace'),
      LLM_API_KEY: 'synthetic-unused-test-key', FISH_API_KEY: 'synthetic-unused-test-key',
      LLM_MULTIMODAL_API_KEY: 'synthetic-unused-test-key' } });
    const child = app.process(); owned.add(child.pid);
    child.on('exit', (code, signal) => record('electron-exit', { pid: child.pid, code, signal }));
    app.on('close', () => record('playwright-close'));
    page = await app.firstWindow();
    await page.waitForURL(/\/index\.html$/);
    page.on('close', () => record('page-close'));
    page.on('crash', () => record('page-crash'));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().forEach(window => window.hide()));
    const call = (method, params) => page.evaluate(([method, params]) => window.lobuddy.request(method, params, crypto.randomUUID()), [method, params]);
    await call('learning.configure', { enabled: false });
    while ((performance.now() - start) / 1000 < duration) {
      if (terminationRequested) throw new Error('runner_interrupted');
      const session = await call('session.create', { title: '持续运行合成验收' });
      const turn = await call('turn.send', { session_id: session.id, text: '归纳测试资料', lane: 'background',
        workflow_id: 'source-digest', workflow_input: { sources: ['note.txt'] } });
      let final;
      for (let i = 0; i < 100; i++) {
        final = await call('task.get', { turn_id: turn.turn_id });
        if (!['queued', 'running'].includes(final.status)) break;
        await pause(50);
      }
      assert.equal(final.status, 'completed');
      assert.equal((await call('task.outcome', { turn_id: turn.turn_id })).verdict, 'verified');
      assert.equal((await call('learning.get', {})).state, 'disabled');
      if ((await call('service.health', {})).voice_available) assert.equal((await call('voice.get', {})).state, 'off');
      state.tasks++;
      const tree = processTree(child.pid); tree.forEach(row => owned.add(row[0]));
      state.samples.push({ seconds: (performance.now() - start) / 1000,
        rss_kib: tree.reduce((sum, row) => sum + row[2], 0), processes: tree.length });
      save();
      if (state.tasks % 20 === 0) console.log(`SOAK ${Math.round(state.samples.at(-1).seconds)}s / ${state.tasks} verified tasks`);
      if (fault && !faultInjected) {
        faultInjected = true; record('fault-injected', { fault });
        if (fault === 'quit') await app.evaluate(({ app }) => app.quit()).catch(() => undefined);
        if (fault === 'electron') child.kill('SIGKILL');
        if (fault === 'renderer') await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()
          .find(window => /\/index\.html$/.test(window.webContents.getURL())).webContents.forcefullyCrashRenderer()).catch(() => undefined);
        if (fault === 'python') {
          const service = readEvents(eventPath).find(event => event.kind === 'child-start' && event.role === 'python');
          assert.ok(service?.pid); process.kill(service.pid, 'SIGKILL');
        }
        await pause(1000);
        // This probe must fail after the injected lifecycle transition.
        try { await call('service.health', {}); }
        catch (error) { state.fault_probe_failed = true; throw error; }
        throw new Error('fault_probe_did_not_fail');
      }
      await pause(Math.min(interval * 1000, Math.max(1, duration * 1000 - (performance.now() - start))));
    }
    assert.ok(!fault && !terminationRequested, 'run interrupted or fault not exercised');
    const verdict = resourceVerdict(state.samples, (performance.now() - start) / 1000, duration);
    assert.ok(verdict.passed, verdict.reason);
    Object.assign(state, { resources: verdict, status: duration >= 7200 ? 'passed' : 'short_check_passed' });
  } catch (error) {
    // Only fixed error categories are persisted, never model data or request arguments.
    const category = /closed/.test(String(error)) ? 'target_closed' : /crash/i.test(String(error)) ? 'target_crashed'
      : error.name === 'AssertionError' ? 'assertion_failed' : 'request_or_runtime_failure';
    Object.assign(state, { status: 'failed', error_category: category });
    record('test-failed', { category });
  } finally {
    state.incident = classify(readEvents(eventPath));
    const cleanupStarted = performance.now();
    cleanup = true; record('cleanup-start'); save();
    if (app) {
      // Tag native shutdown events separately so test cleanup cannot explain the incident.
      await app.evaluate(({ ipcMain }) => ipcMain.emit('test-cleanup')).catch(() => undefined);
      await app.close().catch(() => { record('cleanup-close-failed'); });
    }
    state.cleanup_seconds = (performance.now() - cleanupStarted) / 1000;
    await pause(1000);
    const alive = new Set(processRows().map(row => row[0]));
    state.orphans = [...owned].filter(pid => alive.has(pid));
    if (state.orphans.length) state.status = 'failed';
    if (fault) {
      const expected = { quit: 'app_quit_observed', renderer: 'renderer_exit', python: 'python_exit', electron: 'electron_exit' }[fault];
      if (faultInjected && state.fault_probe_failed && state.incident === expected && !state.orphans.length && state.status === 'failed'
        && (fault !== 'python' || state.cleanup_seconds < 5)) state.status = 'fault_check_passed';
    }
    state.ended_at = new Date().toISOString(); save();
    for (const [signal, handler] of signals) process.removeListener(signal, handler);
    rmSync(temporary, { recursive: true, force: true });
  }
  console.log(JSON.stringify({ status: state.status, tasks: state.tasks, incident: state.incident, report }));
  if (state.status === 'failed') process.exitCode = 1;
})().catch(() => { console.error('Runtime test setup/cleanup failed; inspect lifecycle evidence.'); process.exitCode = 1; });
