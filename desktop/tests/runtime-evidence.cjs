// Diagnostics for isolated native tests. Never persist arguments, text or credentials.
const fs = require('node:fs');

function readEvents(path) {
  if (!fs.existsSync(path)) return [];
  return fs.readFileSync(path, 'utf8').split('\n').filter(Boolean).flatMap(line => {
    try { return [JSON.parse(line)]; } catch { return []; }
  });
}

function classify(events) {
  const beforeCleanup = events.filter(event => !event.cleanup);
  if (beforeCleanup.some(event => event.kind === 'runner-signal')) return 'runner_interrupted';
  if (beforeCleanup.some(event => event.kind === 'render-gone' && event.reason !== 'clean-exit')) return 'renderer_exit';
  if (beforeCleanup.some(event => event.kind === 'child-exit' && event.role === 'python'
    && (event.signal || event.code !== 0))) return 'python_exit';
  if (beforeCleanup.some(event => event.kind === 'electron-exit' && (event.signal || event.code !== 0))) return 'electron_exit';
  if (beforeCleanup.some(event => event.kind === 'before-quit')) return 'app_quit_observed';
  if (beforeCleanup.some(event => event.kind === 'page-close')) return 'page_closed_cause_unknown';
  return 'unclassified';
}

function resourceVerdict(samples, elapsedSeconds, requiredSeconds) {
  if (elapsedSeconds < requiredSeconds || samples.length < 3) return { passed: false, reason: 'insufficient_duration_or_samples' };
  const count = Math.min(20, Math.floor(samples.length / 3));
  const mean = rows => rows.reduce((sum, row) => sum + row.rss_kib, 0) / rows.length;
  const growth = mean(samples.slice(-count)) - mean(samples.slice(count, count * 2));
  return { passed: growth < 65536, rss_growth_kib: growth, reason: growth < 65536 ? 'within_fixed_limit' : 'rss_growth_exceeded' };
}

function bootstrapSource({ profile, appPath, mainPath, eventPath }) {
  return `
const fs = require('node:fs');
const electron = require('electron');
const cp = require('node:child_process');
let cleanup = false;
const record = (kind, fields = {}) => fs.appendFileSync(${JSON.stringify(eventPath)}, JSON.stringify({ at: new Date().toISOString(), kind, cleanup, ...fields }) + '\\n');
electron.ipcMain.on('test-cleanup', () => { cleanup = true; });
const spawn = cp.spawn;
cp.spawn = function(executable, args, options) {
  const child = spawn.call(this, executable, args, options);
  const role = /python/i.test(executable) ? 'python' : 'runtime';
  record('child-start', { pid: child.pid, role });
  child.on('exit', (code, signal) => record('child-exit', { pid: child.pid, role, code, signal }));
  child.on('error', () => record('child-error', { pid: child.pid, role }));
  return child;
};
electron.app.setPath('userData', ${JSON.stringify(profile)});
electron.app.setAppPath(${JSON.stringify(appPath)});
for (const kind of ['before-quit','will-quit','quit','window-all-closed']) electron.app.on(kind, () => record(kind));
electron.app.on('child-process-gone', (_event, info) => record('child-process-gone', { reason: info.reason, code: info.exitCode, role: info.type }));
electron.app.on('web-contents-created', (_event, contents) => {
  contents.on('render-process-gone', (_event, info) => record('render-gone', { id: contents.id, reason: info.reason, code: info.exitCode }));
});
electron.app.on('browser-window-created', (_event, window) => {
  const id = window.id;
  window.on('closed', () => record('window-closed', { id }));
  window.on('unresponsive', () => record('window-unresponsive', { id }));
});
electron.app.whenReady().then(() => {
  for (const kind of ['suspend','resume']) electron.powerMonitor.on(kind, () => record(kind));
});
record('bootstrap');
require(${JSON.stringify(mainPath)});
`;
}

module.exports = { readEvents, classify, resourceVerdict, bootstrapSource };
