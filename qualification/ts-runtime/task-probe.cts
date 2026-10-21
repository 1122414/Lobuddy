import { app, utilityProcess, MessageChannelMain } from 'electron';
import { mkdtemp, mkdir, readFile, writeFile, rm, readdir, lstat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { once } from 'node:events';
import { parseEnv } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import assert from 'node:assert/strict';

let phase = 'startup';
void app.whenReady().then(async () => {
  const root = resolve(__dirname, '../../..');
  const directory = await mkdtemp(join(tmpdir(), 'lobuddy-task-native-'));
  phase = 'load-service';
  const { RpcClient, portTransport } = await import('@lobuddy/service');
  phase = 'configuration';
  const config = parseEnv(await readFile(join(root, '.env'), 'utf8'));
  if (!config.LLM_API_KEY) {
    const vaultModule = join(root, 'desktop/dist-electron/desktop/electron/credential-vault.js');
    const { readLegacyCredential } = await import(vaultModule);
    config.LLM_API_KEY = await readLegacyCredential('llm_api_key');
  }
  assert.ok(config.LLM_API_KEY && config.LLM_BASE_URL && config.LLM_MODEL, 'Model configuration required');
  phase = 'native-launch';
  const manifest = JSON.parse(await readFile(join(root, 'qualification/ts-runtime/native-manifest.json'), 'utf8')) as { dsh: { runtimeSha256: string } };
  const data = join(directory, 'data'), workspace = join(directory, 'workspace');
  await mkdir(workspace); await writeFile(join(workspace, 'source.txt'), '原生工具验证编号：TS-417\n决定：保留原件\n待办：校验输出');
  const child = utilityProcess.fork(join(root, 'packages/service/dist/utility-entry.cjs'), [], {
    stdio: 'pipe', env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME }, serviceName: 'Lobuddy TS task probe' });
  const childExit = once(child, 'exit');
  // Child diagnostics are intentionally not copied: model provider errors can contain request material.
  const errors: Buffer[] = []; child.stderr?.on('data', (bytes: Buffer) => { if (errors.length < 8) errors.push(bytes.subarray(0, 512)); });
  const { port1, port2 } = new MessageChannelMain();
  const client = new RpcClient(portTransport(port1, 'electron'), 20_000);
  const deadline = setTimeout(() => { child.kill(); app.exit(1); }, 360_000);
  const evidence: Record<string, unknown> = { runtime: process.versions, checks: [] };
  let enginePid: number | undefined;
  const check = (name: string) => { (evidence.checks as string[]).push(name); console.log(`PASS: ${name}`); };
  try {
    child.postMessage({ kind: 'connect', storage: { data, workspace, logs: join(directory, 'logs'), create: true },
      engine: { binary: join(root, '.local-upgrade/ts-assets/dsh-runtime'), binarySha256: manifest.dsh.runtimeSha256,
        plugin: join(root, 'bridge/dsh/dist/index.js'), applicationRoot: root,
        apiKey: config.LLM_API_KEY, baseUrl: config.LLM_BASE_URL, model: config.LLM_MODEL } }, [port2]);
    await client.start(); check('native MessagePort task capabilities');
    await client.request('settings.patch', { values: { task_timeout: 90 } });
    const session_id = (await client.request('session.create', { title: '合成资料原生验收' })).id;
    async function waitTurn(turn_id: string, approve: boolean) {
      const start = Date.now(); let approvals = 0;
      for (;;) {
        for (const pending of await client.request('approval.list', {})) {
          assert.equal(pending.turn_id, turn_id);
          await client.request('approval.resolve', { approval_id: pending.approval_id, approved: approve }); approvals++;
        }
        const state = await client.request('task.get', { turn_id });
        if (!['queued','running'].includes(state.status)) return { state, approvals };
        if (Date.now() - start > 100_000) throw Error('turn timeout'); await delay(100);
      }
    }
    phase = 'read';
    const read = await client.request('turn.send', { session_id, text: '请用 lobuddy_read_file 读取工作区 source.txt，直接回复里面的验证编号。' });
    const readResult = await waitTurn(read.turn_id, false);
    if (readResult.state.status !== 'completed') console.log('Read status:', readResult.state.status, readResult.state.error);
    assert.equal(readResult.state.status, 'completed'); assert.match(readResult.state.output_text, /TS-417/);
    check('real model reads synthetic file through native guarded tool');
    const launches = await readdir(join(data, 'dsh'));
    for (const launch of launches.filter(name => name.startsWith('bridge-'))) enginePid = Number(await readFile(join(data, 'dsh', launch, 'owner.pid'), 'utf8'));
    assert.ok(enginePid);
    phase = 'reject';
    const denied = await client.request('turn.send', { session_id, text: '请用 lobuddy_write_file 在工作区创建 denied.txt，内容 deny。若审批拒绝请立即停止，不重试。' });
    const deniedResult = await waitTurn(denied.turn_id, false); assert.ok(deniedResult.approvals > 0);
    await assert.rejects(lstat(join(workspace, 'denied.txt')), { code: 'ENOENT' }); check('real model rejected approval has no file effect');
    phase = 'allow';
    const allowed = await client.request('turn.send', { session_id, text: '请用 lobuddy_write_file 在工作区创建 allowed.txt，内容 exactly TS-ALLOW，然后用 lobuddy_read_file 验证该文件。' });
    const allowedResult = await waitTurn(allowed.turn_id, true); assert.ok(allowedResult.approvals > 0); assert.equal(allowedResult.state.status, 'completed');
    assert.match(await readFile(join(workspace, 'allowed.txt'), 'utf8'), /TS-ALLOW/); check('real model approved write and readback');
    phase = 'digest';
    const digest = await client.request('turn.send', { session_id, text: '请调用 lobuddy_digest，sources 为 ["source.txt"]，按它返回的证据报告决定和待办。' });
    assert.equal((await waitTurn(digest.turn_id, false)).state.status, 'completed');
    assert.equal((await client.request('task.outcome', { turn_id: digest.turn_id })).verdict, 'verified'); check('real model task has independently verified source evidence');
    phase = 'image';
    const sharp = (await import('sharp')).default;
    const imagePath = join(directory, 'shapes.png');
    await sharp(Buffer.from('<svg width="400" height="200"><rect width="400" height="200" fill="white"/><rect x="20" y="20" width="150" height="150" fill="red"/><circle cx="295" cy="95" r="75" fill="blue"/></svg>')).png().toFile(imagePath);
    const image = await client.request('image.import', { path: imagePath });
    const visionSession = (await client.request('session.create', { title: '图片验收' })).id;
    const vision = await client.request('turn.send', { session_id: visionSession, text: '只按图片描述左边和右边各是什么颜色、什么形状。', image_id: image.image_id });
    const visionResult = await waitTurn(vision.turn_id, false); assert.equal(visionResult.state.status, 'completed');
    if (!/红|red/i.test(visionResult.state.output_text)) console.log('Synthetic colour response:', visionResult.state.output_text.slice(0, 300));
    for (const word of ['红','蓝','方','圆']) assert.ok(visionResult.state.output_text.includes(word));
    check('native sharp import and real model image recognition');
    phase = 'cancel';
    const cancelled = await client.request('turn.send', { session_id, text: '写一篇很长的、逐条编号的介绍，说明100种不同的桌面文件整理方法。' });
    await delay(400); await client.request('turn.cancel', { turn_id: cancelled.turn_id });
    assert.equal((await waitTurn(cancelled.turn_id, false)).state.status, 'cancelled'); check('real foreground cancellation reaches terminal state');
    phase = 'crash';
    const crashParams = { session_id, text: '请用 lobuddy_write_file 创建 crash.txt，内容 crash。如果被拒绝就停止。' };
    const crashed = await client.request('turn.send', crashParams, 'crash-identity');
    const approvalDeadline = Date.now() + 60_000;
    while (!(await client.request('approval.list', {})).length) {
      assert.ok(Date.now() < approvalDeadline); await delay(100);
    }
    process.kill(enginePid!, 'SIGKILL');
    assert.equal((await waitTurn(crashed.turn_id, false)).state.status, 'failed');
    assert.deepEqual(await client.request('approval.list', {}), []);
    await assert.rejects(lstat(join(workspace, 'crash.txt')), { code: 'ENOENT' });
    assert.equal((await client.request('turn.send', crashParams, 'crash-identity')).turn_id, crashed.turn_id);
    const recovery = await client.request('turn.send', { session_id, text: '请用 lobuddy_read_file 读取 source.txt，只回复验证编号，不执行任何写操作。' });
    assert.notEqual(recovery.engine_id, crashed.engine_id);
    assert.equal((await waitTurn(recovery.turn_id, false)).state.status, 'completed');
    const replacementLaunches = await readdir(join(data, 'dsh'));
    for (const launch of replacementLaunches.filter(name => name.startsWith('bridge-'))) enginePid = Number(await readFile(join(data, 'dsh', launch, 'owner.pid'), 'utf8'));
    check('engine death denies pending approval; duplicate request does not replay; explicit new request recovers');
    phase = 'shutdown';
    client.close(); assert.deepEqual(await childExit, [0]);
    assert.throws(() => process.kill(enginePid!, 0), { code: 'ESRCH' }); check('native business and owned DSH exit without orphan');
    await writeFile(join(root, '.local-upgrade/t4-native-task-result.json'), JSON.stringify(evidence, null, 2) + '\n');
  } finally {
    clearTimeout(deadline); client.close();
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try { await Promise.race([childExit, new Promise<void>(resolve => { timeout = setTimeout(() => { child.kill(); resolve(); }, 10_000); })]); }
    finally { clearTimeout(timeout); }
    await rm(directory, { recursive: true, force: true });
  }
  app.exit(0);
}).catch(error => {
  const code = typeof error?.code === 'string' && /^[A-Z_]+$/.test(error.code) ? error.code : 'REJECTED';
  console.error(`FAIL: native task qualification at ${phase} (${code}); no credentials or provider payload logged.`);
  if (phase === 'configuration' && error instanceof Error && error.message.startsWith('旧钥匙串读取失败')) console.error(error.message);
  if (error instanceof Error) console.error(error.stack?.split('\n').filter(line => /^\s+at /.test(line)).slice(0, 6).join('\n'));
  app.exit(1);
});
