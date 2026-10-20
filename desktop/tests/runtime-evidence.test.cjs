const test = require('node:test');
const assert = require('node:assert/strict');
const { classify, resourceVerdict } = require('./runtime-evidence.cjs');

test('a closed page alone never establishes a process crash or user action', () => {
  assert.equal(classify([{ kind: 'page-close' }]), 'page_closed_cause_unknown');
  assert.equal(classify([{ kind: 'page-close' }, { kind: 'before-quit', cleanup: true }]), 'page_closed_cause_unknown');
  assert.equal(classify([{ kind: 'before-quit' }, { kind: 'page-close' }]), 'app_quit_observed');
  assert.equal(classify([{ kind: 'runner-signal', signal: 'SIGTERM' }, { kind: 'page-close' }]), 'runner_interrupted');
});

test('explicit process evidence distinguishes renderer, Python and Electron exits', () => {
  assert.equal(classify([{ kind: 'render-gone', reason: 'crashed' }, { kind: 'page-close' }]), 'renderer_exit');
  assert.equal(classify([{ kind: 'child-exit', role: 'python', code: null, signal: 'SIGKILL' }]), 'python_exit');
  assert.equal(classify([{ kind: 'electron-exit', code: 1 }]), 'electron_exit');
  assert.equal(classify([{ kind: 'child-exit', role: 'python', code: 0, signal: null }]), 'unclassified');
});

test('short runs cannot satisfy two-hour acceptance; fixed memory threshold remains binding', () => {
  const stable = Array.from({ length: 60 }, () => ({ rss_kib: 100000 }));
  assert.equal(resourceVerdict(stable, 1654, 7200).passed, false);
  assert.equal(resourceVerdict(stable, 7200, 7200).passed, true);
  const growing = stable.map((row, i) => ({ rss_kib: row.rss_kib + (i >= 40 ? 65536 : 0) }));
  assert.equal(resourceVerdict(growing, 7200, 7200).passed, false);
});
