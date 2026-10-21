import { app, utilityProcess, MessageChannelMain } from 'electron';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { once } from 'node:events';
import { parseEnv } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import assert from 'node:assert/strict';

let phase = 'startup';
void app.whenReady().then(async () => {
  const root = resolve(__dirname,'../../..'), directory = await mkdtemp(join(tmpdir(),'lobuddy-evolution-native-'));
  const { RpcClient, portTransport } = await import('@lobuddy/service');
  const config = parseEnv(await readFile(join(root,'.env'),'utf8'));
  if (!config.LLM_API_KEY) {
    const { readLegacyCredential } = await import(join(root,'desktop/dist-electron/desktop/electron/credential-vault.js'));
    config.LLM_API_KEY = await readLegacyCredential('llm_api_key');
  }
  assert.ok(config.LLM_API_KEY && config.LLM_BASE_URL && config.LLM_MODEL);
  const manifest = JSON.parse(await readFile(join(root,'qualification/ts-runtime/native-manifest.json'),'utf8')) as { dsh: { runtimeSha256: string } };
  const data = join(directory,'data'), workspace = join(directory,'workspace');
  let current: { child: Electron.UtilityProcess; client: InstanceType<typeof RpcClient>; exit: Promise<unknown> } | undefined;
  const checks: string[] = [];
  const check = (name: string) => { checks.push(name); console.log(`PASS: ${name}`); };
  const deadline = setTimeout(() => { current?.child.kill(); app.exit(1); },360000);
  const start = async (create: boolean) => {
    const child = utilityProcess.fork(join(root,'packages/service/dist/utility-entry.cjs'),[],{
      stdio: 'pipe',env: { PATH: '/usr/bin:/bin',HOME: process.env.HOME },serviceName: 'Lobuddy TS evolution probe' });
    child.stderr?.on('data',() => {}); const exit = once(child,'exit');
    const { port1,port2 } = new MessageChannelMain(); const client = new RpcClient(portTransport(port1,'electron'),20000);
    current = { child,client,exit };
    child.postMessage({ kind: 'connect',storage: { data,workspace,logs: join(directory,'logs'),create },engine: {
      binary: join(root,'.local-upgrade/ts-assets/dsh-runtime'),binarySha256: manifest.dsh.runtimeSha256,
      plugin: join(root,'bridge/dsh/dist/index.js'),applicationRoot: root,
      apiKey: config.LLM_API_KEY,baseUrl: config.LLM_BASE_URL,model: config.LLM_MODEL,
    } },[port2]);
    await client.start(); return client;
  };
  const stop = async () => {
    if (!current) return;
    current.client.close(); let timer: ReturnType<typeof setTimeout> | undefined;
    try { await Promise.race([current.exit,new Promise<never>((_resolve,reject) => { timer = setTimeout(() => reject(Error('process shutdown timeout')),15000); })]); }
    finally { clearTimeout(timer); current.child.kill(); }
    current = undefined;
  };
  try {
    phase = 'native-init'; const client = await start(true);
    const policy = (await client.request('learning.get',{})).policy;
    await client.request('relationship.configure',{ enabled: false });
    await client.request('companionship.configure',{ ...(await client.request('companionship.get',{})),enabled: false });
    await client.request('learning.configure',{ ...policy,idle_seconds: 1 });
    await writeFile(join(workspace,'a.txt'),'决定：保留原始来源。\n待办：核对引用。');
    await writeFile(join(workspace,'b.txt'),'独立来源。');
    const session = await client.request('session.create',{ title: '合成工作流学习' });
    const execute = async () => {
      const turn = await client.request('turn.send',{ session_id: session.id,text: '归纳指定来源，保留每个引用',workflow_id: 'source-digest',workflow_input: { sources: ['a.txt','./a.txt','b.txt'] } });
      for (let i = 0; i < 100; i++) {
        const state = await client.request('task.get',{ turn_id: turn.turn_id });
        if (!['queued','running'].includes(state.status)) { assert.equal(state.status,'completed'); return { state,outcome: await client.request('task.outcome',{ turn_id: turn.turn_id }) }; }
        await delay(50);
      }
      throw Error('workflow timed out');
    };
    phase = 'source-trace'; const original = await execute(); assert.equal(original.outcome.verdict,'verified'); assert.equal(original.outcome.metrics.physical_reads,3);
    check('real business execution produces verified duplicate-source evidence');
    phase = 'model-proposal'; let optimized;
    for (let i = 0; i < 120; i++) {
      const versions = await client.request('workflow.list',{});
      optimized = versions.find(value => value.definition.name === 'source-digest' && value.active && value.status === 'probation');
      const failed = (await client.request('learning.get',{})).jobs.find(job => job.kind === 'workflow_proposal' && job.status === 'failed');
      if (failed) { console.error(failed.error); throw Error('proposal failed'); }
      if (optimized) break; await delay(500);
    }
    assert.ok(optimized); assert.equal(optimized.evaluation.cases,40); assert.equal(optimized.evaluation.before,110); assert.equal(optimized.evaluation.after,75);
    check('budgeted real model proposes a trace-backed method and fixed forty-case evaluation promotes it');
    await client.request('learning.configure',{ ...policy,enabled: false });
    phase = 'new-task'; const improved = await execute(); assert.equal(improved.outcome.metrics.physical_reads,2);
    assert.deepEqual(improved.outcome.evidence.filter(item => typeof item.ref === 'string').map(item => item.ref),['S1','S2','S3']);
    check('new task pins promoted version and reduces reads while preserving every source reference');
    phase = 'rollback'; await client.request('workflow.rollback',{ version_id: optimized.version_id });
    const restored = await execute(); assert.equal(restored.outcome.metrics.physical_reads,3);
    check('explicit rollback restores the baseline method for subsequent tasks');
    phase = 'no-improvement';
    const baseline = (await client.request('workflow.list',{})).find(value => value.definition.name === 'source-digest' && value.active)!;
    const unchanged = await client.request('workflow.propose',{ definition: baseline.definition,reason: '合成验收：没有改变工作方式' },original.state.turn_id);
    const rejected = await client.request('workflow.evaluate',{ version_id: unchanged.version_id }); assert.equal(rejected.status,'rejected'); assert.equal(rejected.evaluation.reason,'无任务级改善');
    check('real trace alone cannot promote a method with no measured improvement');
    const candidates = await client.request('skill.candidates',{}); assert.ok(candidates.some(candidate => candidate.evidence.turn_id === original.state.turn_id));
    const candidate = candidates.find(candidate => candidate.evidence.turn_id === original.state.turn_id)!;
    await client.request('skill.candidate.resolve',{ candidate_id: candidate.id,approved: true });
    const skills = await client.request('skill.list',{}); assert.ok(skills.some(skill => skill.name === candidate.proposed_name && skill.success_count === 0));
    check('source-backed skill candidate can be reviewed without claiming verified skill success');
    phase = 'shutdown'; await stop(); check('native evolution owner and runtime close cleanly');
    await writeFile(join(root,'.local-upgrade/t7-native-evolution-result.json'),JSON.stringify({ runtime: process.versions,checks,comparison: optimized.evaluation },null,2) + '\n');
  } finally { clearTimeout(deadline); await stop(); await rm(directory,{ recursive: true,force: true }); }
  app.exit(0);
}).catch(() => { console.error(`Evolution probe failed at ${phase}; credentials and dialogue content omitted.`); app.exit(1); });
