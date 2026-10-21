import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MessageChannel, Worker } from 'node:worker_threads';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { ChatSessionSchema, type Method } from '@lobuddy/contracts';
import { RpcClient, RpcServer, RpcFault, portTransport, type Handlers } from './index.js';

const health = () => ({ protocol: 2, engine: 'test', connected: false, voice_available: false, model_configured: false });
async function pair(handlers: Handlers, timeout = 1000) {
  const channel = new MessageChannel();
  const server = new RpcServer(portTransport(channel.port1, 'node'), handlers);
  const client = new RpcClient(portTransport(channel.port2, 'node'), timeout);
  await client.start();
  return { server, client, channel, close: async () => { client.close(); await server.close(); } };
}

test('duplicate writes share one result; request conflict and unknown methods do not execute', async () => {
  let calls = 0;
  const system = await pair({ 'session.create': ({ title }) => {
    calls++; return ChatSessionSchema.parse({ id: 'synthetic', title });
  } });
  try {
    const [first, repeat] = await Promise.all([system.client.request('session.create', { title: 'same' }, 'write'),
      system.client.request('session.create', { title: 'same' }, 'write')]);
    assert.deepEqual(first, repeat); assert.equal(calls, 1);
    await assert.rejects(system.client.request('session.create', { title: 'different' }, 'write'), { code: 'id_conflict' });
    await assert.rejects(system.client.request('toString' as Method, {}), { code: 'invalid_request' });
    await assert.rejects(system.client.request('focus.get', {}), { code: 'unsupported_method' });
    assert.equal(calls, 1);
  } finally { await system.close(); }
});

test('timed-out writes retain identity and late responses do not retry or resolve another request', async () => {
  let finish: ((value: ReturnType<typeof ChatSessionSchema.parse>) => void) | undefined;
  let calls = 0;
  const system = await pair({ 'service.health': health, 'session.create': () => {
    calls++; return new Promise(resolve => { finish = resolve; });
  } }, 100);
  try {
    await assert.rejects(system.client.request('session.create', {}, 'slow'), { code: 'timeout' });
    finish!(ChatSessionSchema.parse({ id: 'old' }));
    assert.equal((await system.client.request('service.health', {})).protocol, 2);
    await assert.rejects(system.client.request('session.create', {}, 'slow'), { code: 'timeout' });
    assert.equal(calls, 1);
  } finally { await system.close(); }
});

test('server rejects malformed parameters and does not leak handler exceptions', async () => {
  const system = await pair({ 'service.health': health, 'session.create': () => { throw new Error('secret-provider-diagnostic'); } });
  try {
    await assert.rejects(system.client.request('session.create', {}), (error: RpcFault) =>
      error.code === 'internal_error' && !error.message.includes('secret'));
    const response = once(system.channel.port2, 'message');
    system.channel.port2.postMessage({ kind: 'request', protocol: 2, instance_id: system.client.instanceId,
      jsonrpc: '2.0', id: 'invalid', method: 'session.create', params: { title: 42 } });
    assert.equal((await response)[0].outcome.code, 'invalid_request');
  } finally { await system.close(); }
});

test('more than 8192 transient reads do not exhaust request retention', async () => {
  const system = await pair({ 'service.health': health });
  try {
    for (let index = 0; index < 8300; index++) assert.equal((await system.client.request('service.health', {}, `read-${index}`)).protocol, 2);
  } finally { await system.close(); }
});

test('event gaps require authoritative resync; late events from another instance are ignored', async () => {
  const system = await pair({ 'service.health': health });
  const events: unknown[] = [], resync: unknown[] = [];
  system.client.on('event', event => events.push(event));
  system.client.on('resync', reason => resync.push(reason));
  const event = { session_id: 's', task_id: 't', turn_id: 'r', delegation_id: '', run_id: '', project_id: '', kind: 'changed', data: {} };
  try {
    system.channel.port1.postMessage({ kind: 'event', instance_id: randomUUID(), event: { ...event, sequence: 100 } });
    system.server.publish(event);
    await system.client.request('service.health', {});
    assert.equal(events.length, 1);
    const disconnected = once(system.client, 'connected');
    system.channel.port1.postMessage({ kind: 'event', instance_id: system.client.instanceId, event: { ...event, sequence: 3 } });
    assert.deepEqual(await disconnected, [false]);
    assert.deepEqual(resync, ['event-gap']);
    await assert.rejects(system.client.request('service.health', {}), { code: 'unavailable' });
  } finally { await system.close(); }
});

test('closing aborts owned handlers and rejects pending work without re-execution', async () => {
  let entered!: () => void;
  const started = new Promise<void>(resolve => { entered = resolve; });
  let aborted = false;
  const system = await pair({ 'session.create': (_params, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => { aborted = true; reject(new RpcFault('cancelled')); }, { once: true }); entered();
  }) });
  const result = system.client.request('session.create', {});
  const rejection = assert.rejects(result, { code: 'unavailable' });
  await started; await system.close(); await rejection;
  assert.equal(aborted, true);
});

test('Node worker host starts, reports only implemented capability and exits; restart has a new instance', async () => {
  const instances: string[] = [];
  for (let i = 0; i < 2; i++) {
    const worker = new Worker(new URL('./node-host.js', import.meta.url));
    const client = new RpcClient(portTransport({
      postMessage: value => worker.postMessage(value), start: () => {}, close: () => {},
      on: (event, listener) => worker.on(event === 'close' ? 'exit' : event, listener),
      off: (event, listener) => worker.off(event === 'close' ? 'exit' : event, listener),
    }, 'node'));
    try {
      await client.start(); instances.push(client.instanceId!);
      assert.deepEqual(client.methods, ['service.health']);
      assert.equal((await client.request('service.health', {})).connected, false);
      const exited = once(worker, 'exit'); client.close(); assert.deepEqual(await exited, [0]);
    } finally { client.close(); await worker.terminate(); }
  }
  assert.notEqual(instances[0], instances[1]);
});

test('old handshake versions and malformed results terminate the channel', async () => {
  const channel = new MessageChannel();
  const client = new RpcClient(portTransport(channel.port1, 'node'));
  const started = client.start();
  channel.port2.postMessage({ kind: 'ready', protocol: 1, instance_id: randomUUID(), capabilities: [], methods: [], sequence: 0 });
  await assert.rejects(started, { code: 'unavailable' });
  channel.port2.close();
  const system = await pair({ 'service.health': () => new Promise(() => {}) });
  const result = system.client.request('service.health', {}, 'invalid-result');
  const rejected = assert.rejects(result, { code: 'unavailable' });
  system.channel.port1.postMessage({ kind: 'response', jsonrpc: '2.0', instance_id: system.client.instanceId,
    id: 'invalid-result', outcome: { ok: true, result: { protocol: 'wrong' } } });
  await rejected; await system.close();
});
