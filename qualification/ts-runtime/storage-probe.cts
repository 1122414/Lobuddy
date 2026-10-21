import { app, utilityProcess, MessageChannelMain } from 'electron';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';

void app.whenReady().then(async () => {
  const directory = await mkdtemp(join(tmpdir(), 'lobuddy-storage-native-'));
  const { RpcClient, portTransport } = await import('@lobuddy/service');
  const nativeModule = resolve(__dirname, '../../../desktop/dist-electron/desktop/electron/credential-vault.js');
  const { openCredentialVault } = await import(nativeModule);
  try {
    const vault = await openCredentialVault(join(directory, 'credentials.json'));
    const synthetic = `synthetic-${randomUUID()}`;
    await vault.set('llm_api_key', synthetic);
    assert.equal(await vault.get('llm_api_key'), synthetic);
    assert.equal((await readFile(join(directory, 'credentials.json'))).includes(Buffer.from(synthetic)), false);
    assert.equal((await stat(join(directory, 'credentials.json'))).mode & 0o777, 0o600);
    let sessionId = '';
    for (let attempt = 0; attempt < 2; attempt++) {
      const child = utilityProcess.fork(resolve(__dirname, '../../../packages/service/dist/utility-entry.cjs'), [], {
        stdio: 'pipe', env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME }, serviceName: 'Lobuddy TS storage probe' });
      child.stderr?.on('data', (bytes: Buffer) => process.stderr.write(bytes));
      const { port1, port2 } = new MessageChannelMain();
      const client = new RpcClient(portTransport(port1, 'electron'), 5000);
      const deadline = setTimeout(() => { child.kill(); app.exit(1); }, 15_000);
      try {
        child.postMessage({ kind: 'connect', storage: { data: join(directory, 'data'), workspace: join(directory, 'workspace'),
          logs: join(directory, 'logs'), create: attempt === 0 } }, [port2]);
        await client.start();
        if (attempt === 0) {
          sessionId = (await client.request('session.create', { title: '原生存储验收' })).id;
          await client.request('settings.patch', { values: { pet_name: '浊蒂' } });
        } else {
          assert.equal((await client.request('session.list', {}))[0]!.id, sessionId);
          assert.equal((await client.request('settings.get', {})).values.pet_name, '浊蒂');
        }
        const exited = once(child, 'exit'); client.close(); assert.deepEqual(await exited, [0]);
      } finally { clearTimeout(deadline); client.close(); child.kill(); }
    }
    console.log('PASS: native utilityProcess storage, retained IDs/settings after restart, exclusive lease released, main-only safeStorage readback and private ciphertext.');
  } finally { await rm(directory, { recursive: true, force: true }); }
  app.exit(0);
}).catch(() => { console.error('FAIL: native storage qualification; no credentials logged.'); app.exit(1); });
