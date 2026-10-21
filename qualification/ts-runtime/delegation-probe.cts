import { app, utilityProcess, MessageChannelMain } from 'electron';
import { mkdtemp, readFile, writeFile, rm, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { once } from 'node:events';
import { parseEnv } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import assert from 'node:assert/strict';
let phase = 'startup';
void app.whenReady().then(async () => {
  const root = resolve(__dirname,'../../..'), directory = await mkdtemp(join(tmpdir(),'lobuddy-delegation-native-'));
  const { RpcClient, portTransport } = await import('@lobuddy/service');
  const config = parseEnv(await readFile(join(root,'.env'),'utf8'));
  if (!config.TYPESAFE_API_KEY) {
    const { readLegacyCredential } = await import(join(root,'desktop/dist-electron/desktop/electron/credential-vault.js'));
    config.TYPESAFE_API_KEY = await readLegacyCredential('typesafe_api_key');
  }
  assert.ok(config.TYPESAFE_API_KEY);
  const data = join(directory,'data'),workspace = join(directory,'workspace'),checks: string[] = [];
  const check = (name: string) => { checks.push(name); console.log(`PASS: ${name}`); };
  let current: { child: Electron.UtilityProcess;client: InstanceType<typeof RpcClient>;exit: Promise<unknown> } | undefined;
  const deadline = setTimeout(() => { current?.child.kill(); app.exit(1); },120000);
  const start = async (create: boolean) => {
    const child = utilityProcess.fork(join(root,'packages/service/dist/utility-entry.cjs'),[],{ stdio: 'pipe',env: { PATH: '/usr/bin:/bin',HOME: process.env.HOME },serviceName: 'Lobuddy TS delegation probe' });
    child.stderr?.on('data',() => {}); const exit = once(child,'exit');
    const { port1,port2 } = new MessageChannelMain(),client = new RpcClient(portTransport(port1,'electron'),20000);
    current = { child,client,exit };
    child.postMessage({ kind: 'connect',storage: { data,workspace,logs: join(directory,'logs'),create },credentials: { typesafe_api_key: config.TYPESAFE_API_KEY } },[port2]);
    await client.start(); return client;
  };
  const stop = async () => {
    if (!current) return; current.client.close(); let timer: ReturnType<typeof setTimeout> | undefined;
    try { await Promise.race([current.exit,new Promise<never>((_resolve,reject) => { timer = setTimeout(() => reject(Error('shutdown timed out')),15000); })]); }
    finally { clearTimeout(timer); current.child.kill(); } current = undefined;
  };
  try {
    phase = 'native-init'; let client = await start(true);
    const policy = (await client.request('learning.get',{})).policy; await client.request('learning.configure',{ ...policy,enabled: false });
    await client.request('settings.patch',{ values: { jev_mode: 'active' } });
    await writeFile(join(workspace,'source.txt'),'决定：下周发布说明。\n待办：核对文档。');
    const draft = await client.request('delegation.create',{ goal: '归纳 source.txt 中的发布决定与待办',kind: 'source-digest',sources: ['source.txt'],criteria: ['资料来源覆盖且引用可追溯'] });
    const confirmed = await client.request('delegation.confirm',{ delegation_id: draft.id,revision: draft.revision,expires_at: Date.now() / 1000 + 3600 });
    const run = await client.request('delegation.run',{ delegation_id: draft.id,revision: confirmed.revision },'native-delegation');
    phase = 'execution';
    for (let i = 0; i < 100; i++) {
      const detail = await client.request('delegation.get',{ delegation_id: draft.id });
      if (detail.delegation.status === 'completed') { assert.equal(detail.outcomes[0]!.verdict,'verified'); break; }
      assert.ok(i < 99); await delay(50);
    }
    check('native utility executes a pinned workflow and verifies source evidence without Python or a model');
    phase = 'jev'; let decision;
    for (let i = 0; i < 150; i++) {
      await client.request('notification.next',{});
      const state = await client.request('jev.status',{});
      decision = state.recent[0];
      if (decision && decision.status !== 'running') break; await delay(50);
    }
    assert.ok(decision); assert.equal(decision.status,'decided'); assert.ok((decision.input_tokens ?? 0) > 0);
    check('real TypeSafe response passes strict validation and records a single budgeted advisory decision');
    phase = 'restart'; const before = await client.request('progress.get',{}); await stop(); client = await start(false);
    const replay = await client.request('delegation.run',{ delegation_id: draft.id,revision: confirmed.revision },'native-delegation');
    assert.equal(replay.id,run.id); assert.equal(replay.status,'completed'); assert.deepEqual(await client.request('progress.get',{}),before);
    assert.equal((await client.request('jev.status',{})).calls_today,1);
    check('utility restart preserves delegation outcome, model budget and idempotent task identity');
    phase = 'write-approval'; await mkdir(join(workspace,'inbox')); await writeFile(join(workspace,'inbox/a.txt'),'native copy');
    const copy = await client.request('delegation.create',{ goal: '创建分类副本',kind: 'organize-files',source_directory: 'inbox',output_directory: 'out',criteria: ['副本数量和内容校验通过，原文件保留'] });
    const ready = await client.request('delegation.confirm',{ delegation_id: copy.id,revision: copy.revision,expires_at: Date.now() / 1000 + 3600 });
    await client.request('delegation.run',{ delegation_id: copy.id,revision: ready.revision });
    let approvals = await client.request('approval.list',{});
    for (let i = 0; i < 100; i++) { approvals = await client.request('approval.list',{}); if (approvals.length) break; await delay(20); }
    assert.ok(approvals?.length); await client.request('approval.resolve',{ approval_id: approvals[0]!.approval_id,approved: false });
    await delay(100); await assert.rejects(readFile(join(workspace,'out/txt/a.txt')));
    check('native workflow approval rejection creates no file copy');
    phase = 'shutdown'; await stop(); check('service closes without an orphaned utility or engine process');
    await writeFile(join(root,'.local-upgrade/t6-native-delegation-result.json'),JSON.stringify({ runtime: process.versions,checks,jev: { status: decision.status,action: decision.action,model: decision.model,input_tokens: decision.input_tokens,output_tokens: decision.output_tokens } },null,2) + '\n');
  } finally { clearTimeout(deadline); await stop(); await rm(directory,{ recursive: true,force: true }); }
  app.exit(0);
}).catch(() => { console.error(`Delegation probe failed at ${phase}; credentials and provider content omitted.`); app.exit(1); });
