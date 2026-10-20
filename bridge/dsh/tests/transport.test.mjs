import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BridgeTransport } from '../dist/transport.js';

async function fixture(t) {
  const directory = await mkdtemp(join(tmpdir(), 'lobuddy-transport-'));
  const token = 'test-token'.repeat(5);
  let calls = 0, disconnects = 0;
  const server = new BridgeTransport(token, join(directory, 'ready.json'), async () => ({ count: ++calls }), () => { disconnects++; });
  await server.start();
  t.after(async () => { await server.close(); await rm(directory, { recursive: true }); });
  const { port } = JSON.parse(await readFile(join(directory, 'ready.json'), 'utf8'));
  return { server, directory, url: `http://127.0.0.1:${port}`, headers: { Authorization: `Bearer ${token}` },
    calls: () => calls, disconnects: () => disconnects };
}

test('private ready file and authentication including browser origin', async (t) => {
  const f = await fixture(t);
  assert.equal((await stat(join(f.directory, 'ready.json'))).mode & 0o777, 0o600);
  for (const headers of [{}, { Authorization: 'Bearer wrong' }, { ...f.headers, Origin: 'https://example.com' }]) {
    assert.equal((await fetch(f.url + '/rpc', { method: 'POST', headers, body: '{}' })).status, 403);
  }
  assert.equal(f.calls(), 0);
});

test('identical request is executed once, conflicting reuse rejected', async (t) => {
  const f = await fixture(t);
  const send = (params) => fetch(f.url + '/rpc', { method: 'POST', headers: f.headers,
    body: JSON.stringify({ jsonrpc: '2.0', id: 'same', method: 'work', params }) }).then((r) => r.json());
  const results = await Promise.all([send({}), send({})]);
  assert.deepEqual(results[0], results[1]);
  assert.equal(f.calls(), 1);
  assert.ok((await send({ changed: true })).error);
  assert.equal(f.calls(), 1);
});

test('only one SSE owner and disconnect triggers cancellation', async (t) => {
  const f = await fixture(t);
  const abort = new AbortController();
  const stream = await fetch(f.url + '/events', { headers: f.headers, signal: abort.signal });
  assert.equal(stream.status, 200);
  assert.equal((await fetch(f.url + '/events', { headers: f.headers })).status, 409);
  const reader = stream.body.getReader();
  await reader.read();
  f.server.emit({ kind: 'text.delta', text: 'hello' });
  const received = await reader.read();
  assert.match(new TextDecoder().decode(received.value), /hello/);
  abort.abort();
  for (let i = 0; i < 50 && !f.disconnects(); i++) await new Promise((r) => setTimeout(r, 10));
  assert.ok(f.disconnects() >= 1);
  assert.equal(f.server.connected, false);
  assert.throws(() => f.server.emit({ kind: 'tool.request' }));
});
