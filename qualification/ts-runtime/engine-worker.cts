import type {} from 'electron';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
const parent = process.parentPort;
if (!parent) throw Error('utilityProcess required');
parent.once('message', event => {
  void (async () => {
    const { DshRuntime } = await import('@lobuddy/service');
    const config = event.data as { directory: string; binary: string; binarySha256: string; plugin: string };
    const options = { ...config, home: join(config.directory, 'home'), workspace: config.directory,
      apiKey: 'synthetic-not-for-network', baseUrl: 'https://api.deepseek.com', model: 'deepseek-flash' };
    const runtime = new DshRuntime(options);
    let connected!: () => void;
    const ready = new Promise<void>(resolve => { connected = resolve; });
    try {
      await runtime.start(); const pid = runtime.processId; assert.ok(pid);
      const consume = (async () => { for await (const _event of runtime.events(connected)) assert.fail('No user task was authorized'); })();
      // Attach rejection handler before injecting the process fault.
      const failure = assert.rejects(consume, /断开|中断/);
      await ready; assert.equal(runtime.connected, true);
      await runtime.call('session.open', { sessionId: 'synthetic-crash-test', resume: false });
      process.kill(pid, 'SIGKILL'); await failure; await runtime.close();
      assert.equal(runtime.connected, false); assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
    } finally { await runtime.close(); }
    const starting = new DshRuntime({ ...options, home: join(config.directory, 'starting') });
    const start = starting.start(); void start.catch(() => {}); await delay(10);
    await starting.close(); await start.catch(() => {});
    assert.equal(starting.processId, undefined); assert.equal(starting.connected, false);
    parent.postMessage({ passed: true }); process.exit(0);
  })().catch(() => { parent.postMessage({ passed: false }); process.exit(1); });
});
