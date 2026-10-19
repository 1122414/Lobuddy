const test = require('node:test');
const assert = require('node:assert/strict');
const { once } = require('node:events');
const { spawn } = require('node:child_process');
const { ServiceClient } = require('../dist-electron/desktop/electron/service-client');

test('signal-terminated child rejects new requests and shutdown never waits for another exit', async () => {
  // A real process is needed: signalCode and exitCode have different terminal semantics.
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'pipe' });
  const service = new ServiceClient();
  service.child = child;
  let deadline;
  try {
    const exited = once(child, 'exit');
    child.kill('SIGKILL');
    await exited;
    assert.equal(child.exitCode, null);
    assert.equal(child.signalCode, 'SIGKILL');
    // No request should be retained or written to a terminated process.
    await assert.rejects(service.request('service.health', {}, 'after-exit'), /业务服务不可用/);
    assert.equal(service.pending.size, 0);
    assert.equal(service.requests.size, 0);
    await Promise.race([
      Promise.all([service.stop(), service.stop()]),
      new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('shutdown waited for an already exited child')), 1000); }),
    ]);
    assert.equal(service.connected, false);
  } finally {
    clearTimeout(deadline);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  }
});
