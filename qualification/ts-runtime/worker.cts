import type {} from 'electron';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { DatabaseSync, backup } from 'node:sqlite';
import { setTimeout as delay } from 'node:timers/promises';
import { randomBytes } from 'node:crypto';

const directory = process.env.LOBUDDY_QUALIFY_DIRECTORY!;
const parent = process.parentPort;
if (!parent) throw new Error('Qualification requires utilityProcess');
parent.once('message', async (event) => {
  const port = event.ports[0];
  port.on('message', ({ data }) => { if (data.kind === 'close') { port.close(); process.exit(0); } });
  port.start();
  try { port.postMessage({ ok: true, ...(await qualify()) }); }
  catch (error) { port.postMessage({ ok: false, error: error instanceof Error ? error.message : 'Unknown failure' }); }
});

async function qualify(): Promise<Record<string, unknown>> {
  const db = new DatabaseSync(join(directory, 'test.db'));
  try {
    db.exec("CREATE VIRTUAL TABLE memories USING fts5(text); INSERT INTO memories VALUES ('synthetic recall');");
    assert.equal(db.prepare("SELECT count(*) n FROM memories WHERE memories MATCH 'recall'").get()?.n, 1);
    await backup(db, join(directory, 'backup.db'));
  } finally { db.close(); }
  const restored = new DatabaseSync(join(directory, 'backup.db'), { readOnly: true });
  try { assert.equal(restored.prepare('SELECT count(*) n FROM memories').get()?.n, 1); }
  finally { restored.close(); }

  const ort = await import('onnxruntime-node');
  const vad = await ort.InferenceSession.create(join(directory, 'silero.onnx'), {
    executionProviders: ['cpu'], intraOpNumThreads: 1, interOpNumThreads: 1,
  });
  let silenceProbability: number;
  try {
    const result = await vad.run({ input: new ort.Tensor('float32', new Float32Array(576), [1, 576]),
      h: new ort.Tensor('float32', new Float32Array(128), [1, 1, 128]),
      c: new ort.Tensor('float32', new Float32Array(128), [1, 1, 128]) });
    silenceProbability = Number(result.speech_probs!.data[0]);
    assert.ok(Number.isFinite(silenceProbability) && silenceProbability < 0.6);
  } finally { await vad.release(); }

  const { DeepSeekHarness } = await import('@deepseek-ai/dsh-sdk-client');
  const config = JSON.parse(await readFile(join(directory, 'config.json'), 'utf8')) as {
    plugin: string; disabled: string[]; model?: string; wave?: string; manifest: string;
    corpus?: string; corpusDirectory?: string; corpusOutput: string;
    crash: boolean;
  };
  const home = join(directory, 'dsh-home');
  await mkdir(home, { mode: 0o700 });
  const readyPath = join(home, 'ready.json');
  const token = randomBytes(48).toString('base64url');
  const patch = join(home, 'patch.json');
  await writeFile(patch, JSON.stringify([...config.disabled.map(id => ({ id, disabled: true })),
    { insert: [{ id: 'lobuddy-bridge', name: config.plugin }] }]), { mode: 0o600 });
  const harness = new DeepSeekHarness({
    dshBin: join(__dirname, 'native-entry.cjs'), dshHome: home, processCwd: directory,
    profile: 'sdk', patches: [patch], initializeTimeoutMs: 30_000, requestTimeoutMs: 15_000,
    env: { PATH: '/usr/bin:/bin', HOME: directory, TMPDIR: directory, ELECTRON_RUN_AS_NODE: '1',
      LOBUDDY_QUALIFY_DSH: join(directory, 'dsh-runtime'), LOBUDDY_BRIDGE_TOKEN: token,
      LOBUDDY_QUALIFY_PID: join(home, 'entry.pid'),
      LOBUDDY_BRIDGE_READY: readyPath, LOBUDDY_DSH_MODEL: 'synthetic',
      LOBUDDY_DSH_PROVIDER: 'deepseek-official', LOBUDDY_IMAGE_ROOT: join(directory, 'images'),
      DEEPSEEK_API_KEY: 'synthetic', DSH_TELEMETRY_DISABLED: '1' },
  });
  let runtimePid = 0;
  try {
    await harness.start();
    const deadline = Date.now() + 15_000;
    let ready: { port: number; pid: number; protocol: number } | undefined;
    while (Date.now() < deadline) {
      try { ready = JSON.parse(await readFile(readyPath, 'utf8')); break; }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
      await delay(50);
    }
    assert.ok(ready); runtimePid = ready.pid;
    assert.equal(Number(await readFile(join(home, 'entry.pid'), 'utf8')), runtimePid);
    assert.equal(ready.protocol, 1);
    assert.equal((await stat(readyPath)).mode & 0o777, 0o600);
    const response = await fetch(`http://127.0.0.1:${ready.port}/rpc`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 'qualification', method: 'health', params: {} }),
      signal: AbortSignal.timeout(5_000),
    });
    assert.equal(response.status, 200);
    const payload = await response.json() as { error?: unknown; result?: unknown };
    assert.equal(payload.error, undefined); assert.ok(payload.result);
    const unauthorized = await fetch(`http://127.0.0.1:${ready.port}/rpc`, {
      method: 'POST', body: '{}', signal: AbortSignal.timeout(5_000),
    });
    assert.equal(unauthorized.status, 403);
    if (config.crash) process.kill(runtimePid, 'SIGKILL');
  } finally { await harness.close(); }
  assert.throws(() => process.kill(runtimePid, 0), { code: 'ESRCH' });
  const speech = config.model && config.wave
    ? await (await import('./speech-probe.js')).qualifySpeech(config.model, config.wave, config.manifest)
    : { status: 'not requested' };
  const corpus = config.model && config.corpus && config.corpusDirectory
    ? await (await import('./corpus-probe.js')).qualifyCorpus(config.model, config.corpusDirectory, config.corpus, config.corpusOutput)
    : { status: 'not requested' };
  return { sqlite: 'FTS5 and backup restored', onnx: ort.env.versions.node,
    silenceProbability, dsh: 'native handshake, authenticated health, unauthorized rejected, exited',
    termination: config.crash ? 'injected SIGKILL, SDK cleanup confirmed exit' : 'SDK graceful shutdown',
    execve: 'SDK child PID preserved across native exec', speech, corpus };
}
