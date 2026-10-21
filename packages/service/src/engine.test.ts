import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, type ServerResponse, type RequestListener } from 'node:http';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { BridgeClient } from './engine/transport.js';
import { DISABLED_DSH_ROWS } from './engine/profile.js';

async function server(handler: RequestListener) {
  const value = createServer(handler); value.listen(0, '127.0.0.1'); await once(value, 'listening');
  const address = value.address(); assert.ok(address && typeof address !== 'string');
  return { port: address.port, close: async () => { value.closeAllConnections(); await new Promise<void>(resolve => value.close(() => resolve())); } };
}
test('DSH profile retains every disabled built-in and autonomous driver from the fixed baseline', async () => {
  const baseline = JSON.parse(await readFile('qualification/ts-runtime/runtime-policy.json', 'utf8')) as { disabled: string[] };
  assert.deepEqual(DISABLED_DSH_ROWS, baseline.disabled);
});
test('bridge command authentication, response identity and non-retry survive malformed responses', async () => {
  let calls = 0;
  const http = await server(async (req, res) => {
    calls++; assert.equal(req.headers.authorization, `Bearer ${'x'.repeat(48)}`);
    assert.equal(req.headers.origin, undefined);
    const chunks: Buffer[] = []; for await (const chunk of req) chunks.push(chunk);
    const request = JSON.parse(Buffer.concat(chunks).toString()) as { id: string; method: string };
    if (request.method === 'drop') { req.socket.destroy(); return; }
    res.end(JSON.stringify({ jsonrpc: '2.0', id: request.method === 'wrong-id' ? 'wrong' : request.id, result: { ok: true } }));
  });
  const client = new BridgeClient(http.port, 'x'.repeat(48));
  try {
    assert.deepEqual(await client.call('health', {}), { ok: true });
    await assert.rejects(client.call('wrong-id', {}), /协议/);
    await assert.rejects(client.call('drop', {}), /未自动重试/);
    assert.equal(calls, 3);
  } finally { client.close(); await http.close(); }
});
test('SSE decodes split UTF-8 frames, rejects event gaps and never reconnects', async () => {
  let connections = 0;
  const http = await server((_req, res) => {
    connections++; res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const frame = (sequence: number) => Buffer.from(`data: ${JSON.stringify({ sessionId: 's', taskId: 't', turnId: 'r', sequence, kind: 'text.delta', data: { text: '你好' } })}\n\n`);
    const value = frame(1); const index = value.indexOf(Buffer.from('你好')) + 1;
    res.write(value.subarray(0, index)); res.write(value.subarray(index)); res.end(frame(3));
  });
  const client = new BridgeClient(http.port, 'x'.repeat(48));
  try {
    const values: string[] = [];
    await assert.rejects(async () => { for await (const event of client.events()) values.push(String(event.data.text)); }, /丢失或乱序/);
    assert.deepEqual(values, ['你好']); assert.equal(connections, 1); assert.equal(client.connected, false);
  } finally { client.close(); await http.close(); }
});
test('closing the owned event stream aborts blocked reading and clears readiness', async () => {
  let response: ServerResponse | undefined;
  const http = await server((_req, res) => { response = res; res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write(': connected\n\n'); });
  const client = new BridgeClient(http.port, 'x'.repeat(48));
  try {
    let connected!: () => void;
    const ready = new Promise<void>(resolve => { connected = resolve; });
    const task = (async () => { for await (const _event of client.events(connected)) assert.fail('Unexpected event'); })();
    await ready; assert.equal(client.connected, true); assert.ok(response);
    client.close(); await task; assert.equal(client.connected, false);
    await assert.rejects(client.call('health', {}), /中断/);
  } finally { client.close(); await http.close(); }
});
test('oversized and invalid SSE data fail closed without exposing returned content', async () => {
  for (const body of ['data: ' + 'x'.repeat(1024 * 1024 + 1), 'data: {private-invalid}\n']) {
    const http = await server((_req, res) => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.end(body); });
    const client = new BridgeClient(http.port, 'x'.repeat(48));
    try {
      await assert.rejects(async () => { for await (const _event of client.events()) assert.fail('Unexpected event'); }, error => {
        assert.ok(error instanceof Error); assert.ok(!error.message.includes('private-invalid')); return true;
      });
      assert.equal(client.connected, false);
    } finally { client.close(); await http.close(); }
  }
});
