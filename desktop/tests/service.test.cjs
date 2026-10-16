const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
const { ServiceClient } = require('../dist-electron/desktop/electron/service-client');

test('real Python service validates, deduplicates and survives UI client changes', async () => {
  const root = resolve(__dirname, '../..');
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-electron-service-'));
  const service = new ServiceClient();
  const previousKey = process.env.LLM_API_KEY;
  process.env.LLM_API_KEY = 'synthetic-unused-test-key';
  service.start(process.env.LOBUDDY_PYTHON || resolve(root, '.venv/bin/python'), root, join(temporary, 'data'), join(temporary, 'workspace'));
  if (previousKey === undefined) delete process.env.LLM_API_KEY; else process.env.LLM_API_KEY = previousKey;
  try {
    await service.handshake();
    assert.equal(service.connected, true);
    const first = await service.request('session.create', { title: 'test' }, 'once');
    const repeat = await service.request('session.create', { title: 'test' }, 'once');
    assert.equal(first.id, repeat.id);
    await assert.rejects(service.request('session.create', { title: 'different' }, 'once'), /conflict/);
    await assert.rejects(service.request('shell.execute', {}, 'forbidden'));
    await assert.rejects(service.request('session.create', { title: 'x', unknown: true }, 'invalid'));
    assert.equal((await service.request('session.list', {}, 'read')).length, 1);
    await service.request('session.create', { title: 'next' }, 'next');
    // Read requests don't exhaust the lifetime mutation identity budget.
    assert.equal((await service.request('session.list', {}, 'read')).length, 2);
    assert.ok(service.requests.size < 5);
  } finally { await Promise.all([service.stop(), service.stop()]); rmSync(temporary, { recursive: true }); }
  assert.equal(service.connected, false);
});
