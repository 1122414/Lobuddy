import { app, MessageChannelMain, safeStorage, utilityProcess } from 'electron';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { writeFile } from 'node:fs/promises';
import { qualifyCredentials } from './credential-probe.cjs';

const directory = process.env.LOBUDDY_QUALIFY_DIRECTORY;
if (!directory) throw new Error('An isolated qualification directory is required');
app.setPath('userData', join(directory, 'electron'));
void app.whenReady().then(async () => {
  assert.ok(safeStorage.isEncryptionAvailable(), 'OS credential protection unavailable');
  const secret = 'synthetic-qualification-value';
  const encrypted = safeStorage.encryptString(secret);
  assert.equal(safeStorage.decryptString(encrypted), secret);
  assert.ok(!encrypted.includes(Buffer.from(secret)));
  const credentialMigration = await qualifyCredentials(directory);
  const child = utilityProcess.fork(join(__dirname, 'worker.cjs'), [], {
    serviceName: 'Lobuddy TS qualification', stdio: 'pipe',
    env: { PATH: '/usr/bin:/bin', HOME: directory, TMPDIR: directory,
      LOBUDDY_QUALIFY_DIRECTORY: directory },
  });
  child.stderr?.on('data', (chunk: Buffer) => process.stderr.write(chunk));
  let completed = false;
  const { port1, port2 } = new MessageChannelMain();
  const timeout = setTimeout(() => { child.kill(); app.exit(1); }, 900_000);
  child.once('exit', (code) => {
    clearTimeout(timeout); port1.close();
    if (!completed || code !== 0) console.error('Utility qualification exit', code);
    app.exit(completed && code === 0 ? 0 : 1);
  });
  port1.on('message', async ({ data }: { data: { ok: boolean; [key: string]: unknown } }) => {
    if (!data.ok) { console.error('Qualification failed:', data); child.kill(); return; }
    await writeFile(join(directory, 'result.json'), JSON.stringify({
      electron: process.versions.electron, node: process.versions.node,
      architecture: process.arch, safeStorageRoundtrip: true, utility: data,
      credentialMigration,
    }, null, 2));
    completed = true;
    console.log('QUALIFICATION_RESULT: ' + JSON.stringify(data));
    port1.postMessage({ kind: 'close' });
  });
  port1.start();
  child.postMessage({ kind: 'start' }, [port2]);
}).catch((error: unknown) => { console.error(error); app.exit(1); });
