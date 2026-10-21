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
  const root = resolve(__dirname,'../../..'), directory = await mkdtemp(join(tmpdir(),'lobuddy-companion-native-'));
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
      stdio: 'pipe',env: { PATH: '/usr/bin:/bin',HOME: process.env.HOME },serviceName: 'Lobuddy TS companion probe' });
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
    phase = 'native-init'; let client = await start(true);
    assert.ok(client.methods.includes('relationship.forget')); assert.ok(client.methods.includes('companion.import'));
    const learning = await client.request('learning.get',{});
    await client.request('learning.configure',{ ...learning.policy,enabled: false });
    const one = (await client.request('session.create',{ title: '合成偏好一' })).id;
    const two = (await client.request('session.create',{ title: '合成偏好二' })).id;
    async function turn(session_id: string,text: string) {
      const state = await client.request('turn.send',{ session_id,text }); const began = Date.now();
      for (;;) {
        for (const pending of await client.request('approval.list',{})) await client.request('approval.resolve',{ approval_id: pending.approval_id,approved: false });
        const value = await client.request('task.get',{ turn_id: state.turn_id });
        if (!['running','queued'].includes(value.status)) { assert.equal(value.status,'completed'); return value; }
        if (Date.now() - began > 90000) throw Error('real conversation timed out'); await delay(100);
      }
    }
    phase = 'remember'; await client.request('learning.configure',{ ...learning.policy,enabled: true });
    await turn(one,'以后请叫我小禾');
    assert.match((await turn(two,'根据已保存的明确称呼偏好，我希望你怎么称呼我？只回答称呼。')).output_text,/小禾/);
    check('real model recalls an explicit nickname across isolated sessions');
    phase = 'correct'; await turn(one,'以后请叫我小满');
    const corrected = (await client.request('relationship.list',{})).find(item => item.status === 'active' && item.key === 'nickname')!;
    assert.match(corrected.content,/小满/);
    await stop(); client = await start(false);
    const recalled = await turn(two,'按当前明确偏好，我的称呼是什么？只说当前称呼。');
    assert.match(recalled.output_text,/小满/); assert.doesNotMatch(recalled.output_text,/小禾/);
    check('correction survives native utility restart and overrides old DSH conversation');
    phase = 'forget'; await client.request('relationship.forget',{ relation_id: corrected.id });
    await stop(); client = await start(false);
    const forgotten = await turn(two,'我明确保存过的称呼是什么？没有有效资料就说不知道，不要猜。');
    assert.doesNotMatch(forgotten.output_text,/小禾|小满/);
    assert.equal((await client.request('relationship.list',{})).filter(item => item.status === 'active').length,0);
    check('forgetting survives process restart without restoring blocked history');
    phase = 'proactive-source';
    const memory = await client.request('preference.save',{ kind: 'shared',content: '我们一起整理了蓝色相册。' }); assert.ok(memory);
    await client.request('learning.configure',{ ...learning.policy,idle_seconds: 1 });
    await client.request('companionship.trigger',{ event: 'conversation_finished' });
    const began = Date.now(); let notice;
    while (Date.now() - began < 90000) {
      notice = await client.request('companionship.poll',{});
      if (notice) break; await delay(1000);
    }
    assert.ok(notice); assert.match(notice.text,/相册/);
    const source = await client.request('companionship.source',{ source_id: memory.id }); assert.match(source.label,/蓝色相册/);
    const jobs = (await client.request('learning.get',{})).jobs;
    assert.ok(jobs.some(job => job.kind === 'companion_topic' && job.status === 'completed'));
    check('budgeted real model builds a proactive bubble from a retained experience quote');
    phase = 'shutdown'; await stop(); check('native companion service releases its execution owner on shutdown');
    await writeFile(join(root,'.local-upgrade/t5-native-companion-result.json'),JSON.stringify({ runtime: process.versions,checks },null,2) + '\n');
  } finally { clearTimeout(deadline); await stop(); await rm(directory,{ recursive: true,force: true }); }
  app.exit(0);
}).catch(() => { console.error(`Companion probe failed at ${phase}; credentials and dialogue content omitted.`); app.exit(1); });
