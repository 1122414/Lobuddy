import { app, utilityProcess, MessageChannelMain } from 'electron';
import { resolve } from 'node:path';
import { once } from 'node:events';
import assert from 'node:assert/strict';

void app.whenReady().then(async () => {
  const { RpcClient, portTransport } = await import('@lobuddy/service');
  const instances: string[] = [];
  for (let attempt = 0; attempt < 2; attempt++) {
    const child = utilityProcess.fork(resolve(__dirname, '../../../packages/service/dist/utility-entry.cjs'), [], {
      stdio: 'pipe', env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME }, serviceName: 'Lobuddy TS service probe',
    });
    child.stderr?.on('data', (bytes: Buffer) => process.stderr.write(bytes));
    const { port1, port2 } = new MessageChannelMain();
    const client = new RpcClient(portTransport(port1, 'electron'), 5_000);
    const deadline = setTimeout(() => { child.kill(); app.exit(1); }, 10_000);
    try {
      child.postMessage({ kind: 'connect' }, [port2]);
      await client.start(); instances.push(client.instanceId!);
      assert.deepEqual(client.methods, ['service.health']);
      const health = await client.request('service.health', {});
      assert.equal(health.protocol, 2); assert.equal(health.connected, false);
      const exited = once(child, 'exit'); client.close();
      assert.deepEqual(await exited, [0]);
    } finally { clearTimeout(deadline); client.close(); child.kill(); }
  }
  assert.notEqual(instances[0], instances[1]);
  console.log('PASS: real Electron v2 MessagePort, validated health, explicit unavailable engine, restart isolation, clean exit.');
  app.exit(0);
}).catch((error: unknown) => { console.error(error); app.exit(1); });
