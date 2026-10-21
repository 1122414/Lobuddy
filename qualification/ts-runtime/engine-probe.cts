import { app, utilityProcess } from 'electron';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { once } from 'node:events';
import assert from 'node:assert/strict';
void app.whenReady().then(async () => {
  const root = resolve(__dirname, '../../..'), directory = await mkdtemp(join(tmpdir(), 'lobuddy-engine-fault-'));
  const assets = process.env.LOBUDDY_QUALIFY_ASSETS ?? join(root, '.local-upgrade/ts-assets');
  const manifest = JSON.parse(await readFile(join(root, 'qualification/ts-runtime/native-manifest.json'), 'utf8')) as { dsh: { runtimeSha256: string } };
  const child = utilityProcess.fork(join(__dirname, 'engine-worker.cjs'), [], { stdio: 'pipe', env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME } });
  child.stdout?.resume(); child.stderr?.resume();
  const exit = once(child, 'exit'), message = once(child, 'message');
  const timeout = setTimeout(() => { child.kill(); app.exit(1); }, 60_000);
  try {
    child.postMessage({ directory, binary: join(assets, 'dsh-runtime'), binarySha256: manifest.dsh.runtimeSha256, plugin: join(root, 'bridge/dsh/dist/index.js') });
    assert.deepEqual(await message, [{ passed: true }]); assert.deepEqual(await exit, [0]);
    console.log('PASS: production TS runtime observes native DSH death and cancels startup without orphan; no model request sent.');
  } finally { clearTimeout(timeout); child.kill(); await rm(directory, { recursive: true, force: true }); }
  app.exit(0);
}).catch(() => { console.error('FAIL: native engine fault probe'); app.exit(1); });
