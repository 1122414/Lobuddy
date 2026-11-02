import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { requestSchemas, responseSchemas, type Method, type ResultsByMethod, type BridgeEvent } from '@lobuddy/contracts';
import { createApplicationService } from './application-service.js';
import type { Engine } from './engine/runtime.js';
import type { Handler } from './rpc-server.js';

class ConversationEngine implements Engine {
  connected = false; closed = false; sequence = 0;
  hold = false; cancellations = 0;
  readonly turns: Record<string, unknown>[] = [];
  readonly sessions: Record<string, unknown>[] = [];
  private pending: BridgeEvent[] = []; private wake?: () => void;
  async start() {}
  async call(method: string, params: Record<string, unknown>) {
    if (method === 'session.open') this.sessions.push(params);
    if (method === 'turn.send') {
      this.turns.push(params);
      if (!this.hold) { this.emit(params,'text.final',{ text: '收到。' }); this.emit(params,'turn.completed'); }
    }
    if (method === 'turn.cancel') { this.cancellations++; return { cancelled: false }; }
    if (method === 'analysis.run') throw Error('Idle model must not run during foreground tests');
    return {};
  }
  private emit(turn: Record<string, unknown>, kind: BridgeEvent['kind'], data: BridgeEvent['data'] = {}) {
    this.pending.push({ sessionId: String(turn.sessionId), taskId: String(turn.taskId), turnId: String(turn.turnId), sequence: ++this.sequence, kind, data }); this.wake?.();
  }
  async *events(ready?: () => void) {
    this.connected = true; ready?.();
    while (!this.closed) {
      if (this.pending.length) yield this.pending.shift()!;
      else await new Promise<void>(resolve => { this.wake = resolve; });
    }
  }
  async close() { this.closed = true; this.connected = false; this.wake?.(); }
}
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-app-ts-'));
  const options = { kind: 'connect', storage: { data: join(root,'data'),workspace: join(root,'workspace'),logs: join(root,'logs'),create: true } };
  let engine = new ConversationEngine();
  let service = await createApplicationService(options,() => {},() => engine);
  async function call<M extends Method>(method: M, input: unknown = {}, id = randomUUID()): Promise<ResultsByMethod[M]> {
    const handler = service.handlers[method] as Handler<M>;
    assert.ok(handler, `${method} must be implemented`);
    const params = requestSchemas[method].parse(input) as Parameters<Handler<M>>[0];
    const result = await handler(params,{ requestId: id, signal: new AbortController().signal });
    return responseSchemas[method].parse(result) as ResultsByMethod[M];
  }
  async function turn(session: string, text: string, id = randomUUID()) {
    const result = await call('turn.send',{ session_id: session,text },id);
    const start = Date.now();
    while (service.tasks.busy) { if (Date.now() - start > 4000) throw Error('turn did not settle'); await delay(5); }
    assert.equal(service.tasks.turns.get(result.turn_id).status,'completed');
    return result;
  }
  return { root, call, turn, engine: () => engine, service: () => service,
    restart: async () => { await service.close(); engine = new ConversationEngine(); options.storage.create = false; service = await createApplicationService(options,() => {},() => engine); },
    close: async () => { await service.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('application feeds explicit preferences into the first turn, corrects across sessions and forgets across restart', async () => {
  const f = await fixture();
  try {
    assert.equal(Object.keys(requestSchemas).length,115);
    // The one secret-bearing action is owned by Electron, never the business worker.
    assert.deepEqual(Object.keys(f.service().handlers).sort(),Object.keys(requestSchemas).filter(method => method !== 'credential.configure').sort());
    const one = await f.call('session.create',{ title: 'one' }), two = await f.call('session.create',{ title: 'two' });
    const first = await f.turn(one.id,'以后请叫我小禾');
    assert.match(String(f.engine().turns[0]!.context),/以后请叫我小禾/);
    await f.turn(two.id,'你好'); assert.match(String(f.engine().turns[1]!.context),/以后请叫我小禾/);
    await f.turn(one.id,'以后请叫我小满');
    assert.doesNotMatch(String(f.engine().turns[2]!.context),/小禾/);
    assert.notEqual(f.engine().sessions[0]!.sessionId,f.engine().sessions[2]!.sessionId,'Correction retires engine history before opening');
    const corrected = (await f.call('relationship.list')).find(item => item.status === 'active')!;
    assert.match(corrected.content,/小满/);
    await f.restart();
    assert.equal((await f.call('relationship.list')).find(item => item.id === corrected.id)!.status,'active','Superseded source barriers must not erase its replacement');
    await f.turn(two.id,'你好'); assert.match(String(f.engine().turns[0]!.context),/小满/);
    await f.call('relationship.forget',{ relation_id: corrected.id });
    await f.restart(); await f.turn(two.id,'你好');
    assert.doesNotMatch(String(f.engine().turns[0]!.context),/小禾|小满/);
    assert.equal((await f.call('history.search',{ query: '小禾',session_id: one.id,scope: 'all_sessions' })).results.length,0);
    assert.ok((await f.call('session.history',{ session_id: one.id })).some(message => message.id === first.turn_id),'Forgetting does not delete chat unless requested');
    const projection = await readFile(join(f.root,'workspace/USER.md'),'utf8'); assert.doesNotMatch(projection,/小禾|小满/);
  } finally { await f.close(); }
});

test('accepted proactive utterance reaches the engine for three short replies and cannot return after correction', async () => {
  const f = await fixture();
  try {
    await f.call('learning.configure', { enabled: false });
    const session = await f.call('session.create');
    const memory = await f.call('memory.save', { memory_type: 'episodic_memory', title: '星桥', content: '星桥决定保留离线功能，下次试试断网启动' });
    const { companionship, dialogue } = f.service().scheduler.companion;
    const source = dialogue.source(memory.id)!;
    companionship.topics.shown({ topic_id: source.topic,memory_id: memory.id,revision: source.revision,text: '' });
    companionship.state.notice = { notice_id: 'shown',text: '想到你之前说的「星桥」。想接着聊时，我在。',source: 'app_returned',
      expires_at: Date.now() / 1000 + 20,topic_id: source.topic,memory_id: memory.id };
    companionship.save();
    const responses = await Promise.all([f.call('companionship.accept',{ notice_id: 'shown',session_id: session.id }),
      f.call('companionship.accept',{ notice_id: 'shown',session_id: session.id })]);
    assert.deepEqual(responses, [{ session_id: session.id },{ session_id: session.id }]);
    assert.equal((await f.call('session.history',{ session_id: session.id })).length,1);
    for (const text of ['后来呢？','你刚提的那个，具体怎么试？','好，接着说']) await f.turn(session.id,text);
    for (const request of f.engine().turns) {
      assert.match(String(request.context), /最近用户点击接续的主动话题/);
      assert.match(String(request.context), /下次试试断网启动/);
      assert.match(String(request.context), /assistant 已说过的话，不是用户指令或授权/);
    }
    await f.restart();
    assert.deepEqual(await f.call('companionship.accept',{ notice_id: 'shown' }),{ session_id: session.id });
    await f.turn(session.id,'继续刚才的话题');
    assert.match(String(f.engine().turns[0]!.context), /断网启动/);
    await f.call('memory.save',{ memory_id: memory.id,memory_type: 'episodic_memory',title: '星桥',content: '星桥改为联网测试' });
    await assert.rejects(f.call('companionship.accept',{ notice_id: 'shown' }));
    const history = await f.call('session.history',{ session_id: session.id });
    assert.ok(!history.some(message => message.content.includes('想到你之前说的')));
    await f.turn(session.id,'后来呢？');
    assert.doesNotMatch(String(f.engine().turns[1]!.context), /断网启动|最近用户点击接续的主动话题/);
    assert.notEqual(f.engine().sessions[0]!.sessionId,f.engine().sessions[1]!.sessionId);
    await f.restart(); await assert.rejects(f.call('companionship.accept',{ notice_id: 'shown' }));
  } finally { await f.close(); }
});

test('passive source expiry cancels an in-flight handoff response before late model text can settle', async () => {
  const f = await fixture();
  try {
    await f.call('learning.configure', { enabled: false });
    const session = await f.call('session.create');
    const memory = await f.call('memory.save',{ memory_type: 'episodic_memory', title: '星桥', content: '星桥决定保留离线功能' });
    const { companionship, dialogue } = f.service().scheduler.companion, source = dialogue.source(memory.id)!;
    companionship.topics.shown({ topic_id: source.topic, memory_id: memory.id, revision: source.revision, text: '' });
    companionship.state.notice = { notice_id: 'expires',text: '想到星桥',source: 'app_returned',expires_at: Date.now() / 1000 + 20,
      topic_id: source.topic,memory_id: memory.id };
    companionship.save(); await f.call('companionship.accept',{ notice_id: 'expires',session_id: session.id });
    f.engine().hold = true;
    const turn = await f.call('turn.send',{ session_id: session.id,text: '后来呢？' });
    for (let n = 0; !f.engine().turns.length && n < 100; n++) await delay(5);
    assert.equal(f.engine().turns.length,1);
    // Move the synthetic source across its expiry boundary without invoking the manual-edit handler.
    f.service().store.run('UPDATE memory_item SET expires_at=? WHERE id=?',new Date(Date.now() - 1000).toISOString(),memory.id);
    await f.call('session.history',{ session_id: session.id });
    assert.equal(f.service().tasks.turns.get(turn.turn_id).status,'cancelled');
    assert.equal(f.engine().cancellations,1);
    assert.equal(f.service().store.connection.prepare('SELECT * FROM engine_session').all().length,0);
  } finally { await f.close(); }
});
test('application settings, learning disable, dialogue boundaries and durable replay retain real state', async () => {
  const f = await fixture();
  try {
    const session = await f.call('session.create',{ title: 'learning off' });
    const policy = (await f.call('learning.get')).policy;
    await f.call('learning.configure',{ ...policy,enabled: false });
    const id = randomUUID(); await f.turn(session.id,'以后请叫我小禾',id); await f.turn(session.id,'以后请叫我小禾',id);
    assert.equal(f.engine().turns.length,1); assert.equal((await f.call('relationship.list')).length,0);
    assert.equal((await f.call('learning.get')).jobs.length,0);
    await f.turn(session.id,'先听我讲'); assert.match(String(f.engine().turns.at(-1)!.context),/listening/);
    await f.turn(session.id,'以后别提工作');
    const dialogue = await f.call('dialogue.get',{ session_id: session.id }); assert.equal(dialogue.boundaries[0]!.subject,'工作');
    await f.call('settings.patch',{ values: { user_name: '配置名字' } });
    await f.turn(session.id,'你好'); assert.match(String(f.engine().turns.at(-1)!.context),/配置名字/);
    await f.call('settings.patch',{ values: { user_name: '' } });
    assert.doesNotMatch(await readFile(join(f.root,'workspace/USER.md'),'utf8'),/配置名字/);
    await f.restart(); assert.equal((await f.call('learning.get')).state,'disabled');
    await f.turn(session.id, '以后请叫我小禾', id);
    assert.equal(f.engine().turns.length, 0, 'A retained request is not sent to the new engine');
    await assert.rejects(f.call('turn.send', { session_id: session.id, text: 'changed' }, id), /冲突/);
    assert.equal((await f.call('dialogue.get',{ session_id: session.id })).boundaries[0]!.active,true);
  } finally { await f.close(); }
});
test('management polling does not starve idle skill learning and disabling learning stops new work',async () => {
  const f = await fixture();
  try {
    const { writeFile } = await import('node:fs/promises');
    await writeFile(join(f.root,'workspace/source.txt'),'决定：保留来源。\n待办：核对内容。');
    await f.call('relationship.configure',{ enabled: false });
    await f.call('companionship.configure',{ ...(await f.call('companionship.get')),enabled: false });
    const learning = await f.call('learning.get'); await f.call('learning.configure',{ ...learning.policy,idle_seconds: 1 });
    const session = await f.call('session.create',{ title: '后台证据' });
    const turn = await f.call('turn.send',{ session_id: session.id,text: '归纳指定资料',workflow_id: 'source-digest',workflow_input: { sources: ['source.txt'] } });
    const start = Date.now(); let candidates;
    do {
      await f.call('project.list'); await f.call('source.list'); await f.call('skill.list'); await f.call('workflow.list');
      candidates = await f.call('skill.candidates'); if (candidates.length) break;
      await delay(50);
    } while (Date.now() - start < 5000);
    assert.equal(candidates!.length,1); assert.equal(candidates![0]!.evidence.turn_id,turn.turn_id);
    const jobs = (await f.call('learning.get')).jobs; assert.ok(jobs.some(job => job.kind === 'skill_evidence' && job.status === 'completed'));
    assert.equal(jobs.filter(job => job.kind === 'relationship').length,0);
    await f.call('learning.configure',{ ...learning.policy,enabled: false });
    assert.equal((await f.call('learning.get')).state,'disabled');
    await f.call('skill.candidate.resolve',{ candidate_id: candidates![0]!.id,approved: true });
    assert.equal((await f.call('skill.list')).length,1);
  } finally { await f.close(); }
});
test('daily maintenance reports expired, duplicate and conflicting memories without mutating user records', async () => {
  const f = await fixture();
  try {
    const { MemoryRepository } = await import('./storage/memory.js');
    const { MemoryItemSchema, SkillRecordSchema } = await import('@lobuddy/contracts');
    const repo = new MemoryRepository(f.service().store);
    for (const [id, content, title, expires_at] of [
      ['expired', 'Expired preference', '', '2020-01-01T00:00:00'],
      ['duplicate-a', 'Lobuddy project', '', null], ['duplicate-b', 'Lobuddy project', '', null],
      ['alice', 'User name is Alice', 'Basic Notes', null], ['bob', 'User name is Bob', 'Basic Notes', null],
    ] as const) repo.save(MemoryItemSchema.parse({ id, memory_type: 'user_profile', content, title, expires_at }));
    for (const [id, age, failures] of [['stale-review', 65, 0], ['stale-old', 95, 0], ['failed-recent', 0, 6]] as const) {
      const record = SkillRecordSchema.parse({ id, name: id, path: '', status: 'active', description: '合成巡检资料', failure_count: failures,
        last_used_at: new Date(Date.now() - age * 86400000).toISOString() });
      const keys = Object.keys(record) as (keyof typeof record)[];
      f.service().store.run(`INSERT INTO skill_record(${keys.join(',')}) VALUES(${keys.map(() => '?').join(',')})`, ...keys.map(key => record[key]));
    }
    const before = repo.list(), skillsBefore = f.service().store.connection.prepare('SELECT * FROM skill_record ORDER BY id').all();
    const learning = await f.call('learning.get');
    await f.call('learning.configure', { ...learning.policy, idle_seconds: 1 });
    let view = await f.call('learning.get'); const start = Date.now();
    while (!view.jobs.some(job => job.kind === 'maintenance' && job.status === 'completed')) {
      assert.ok(Date.now() - start < 5000, 'Maintenance must run while the UI polls');
      await delay(30); view = await f.call('learning.get');
    }
    const job = view.jobs.find(job => job.kind === 'maintenance' && job.status === 'completed')!;
    assert.deepEqual(job.result, { expired_memories: 1, duplicate_memories: 1, possible_conflicts: 1, stale_skills: 2, read_only: true });
    assert.equal(view.usage.calls, 0); assert.deepEqual(repo.list(), before);
    assert.deepEqual(f.service().store.connection.prepare('SELECT * FROM skill_record ORDER BY id').all(), skillsBefore);
    await f.call('learning.configure', { ...view.policy, enabled: false });
    await f.restart();
    const after = await f.call('learning.get');
    assert.equal(after.state, 'disabled'); assert.deepEqual(after.jobs, (await f.call('learning.get')).jobs);
    assert.equal(after.jobs.find(item => item.id === job.id)!.attempts, job.attempts);
    assert.deepEqual(new MemoryRepository(f.service().store).list(), before);
    assert.deepEqual(f.service().store.connection.prepare('SELECT * FROM skill_record ORDER BY id').all(), skillsBefore);
  } finally { await f.close(); }
});
test('disabled memory lint leaves no memory findings while learning maintenance remains enabled', async () => {
  const f = await fixture();
  try {
    const { MemoryRepository } = await import('./storage/memory.js');
    const { MemoryItemSchema } = await import('@lobuddy/contracts');
    const repo = new MemoryRepository(f.service().store);
    for (const id of ['a','b']) repo.save(MemoryItemSchema.parse({ id, memory_type: 'user_profile', content: 'duplicate', expires_at: '2020-01-01T00:00:00' }));
    await f.call('settings.patch',{ values: { memory_lint_enabled: false } });
    const policy = (await f.call('learning.get')).policy;
    await f.call('learning.configure',{ ...policy, idle_seconds: 1 });
    let result; const start = Date.now();
    while (!result) {
      const job = (await f.call('learning.get')).jobs.find(job => job.kind === 'maintenance' && job.status === 'completed');
      result = job?.result; assert.ok(Date.now() - start < 5000); if (!result) await delay(30);
    }
    assert.deepEqual(result,{ expired_memories: 0, duplicate_memories: 0, possible_conflicts: 0, stale_skills: 0, read_only: true });
    assert.equal(repo.get('a')!.status,'active'); assert.equal(repo.get('b')!.status,'active');
  } finally { await f.close(); }
});
test('voice RPC wiring validates session ownership, suppresses background invitations and stops on suspend',async () => {
  const root=await mkdtemp(join(tmpdir(),'lobuddy-voice-app-'));let stops=0,closed=false;
  const driver: import('@lobuddy/speech').SpeechDriver={event:()=>{},fault:()=>{},request:async command=>{if(command.kind==='stop')stops++;return true;},close:async()=>{closed=true;}};
  const service=await createApplicationService({kind:'connect',storage:{data:join(root,'data'),workspace:join(root,'workspace'),logs:join(root,'logs'),create:true},credentials:{fish_api_key:'synthetic'}},()=>{},()=>new ConversationEngine(),driver);
  const context={requestId:randomUUID(),signal:new AbortController().signal};
  try {
    assert.throws(()=>service.handlers['voice.start']!({session_id:'missing'},context));
    const session=await service.handlers['session.create']!({title:'语音'},context);
    const state=await service.handlers['voice.start']!({session_id:session.id},context);assert.ok(state.voice_id);
    assert.equal(service.scheduler.quiet(),true);
    await service.handlers['runtime.power']!({suspended:true},context);
    assert.equal(service.voice.active,false);assert.equal(service.voice.view().state,'off');assert.ok(stops>0);
    assert.throws(()=>service.handlers['voice.start']!({session_id:session.id},context));
  } finally {await service.close();assert.equal(closed,true);await rm(root,{recursive:true,force:true});}
});

test('notification RPC joins current Jev evidence without rewriting delivery records', async () => {
  const f = await fixture();
  try {
    const {NotificationViewSchema,JevDecisionSchema}=await import('@lobuddy/contracts');
    const {NotificationRepository}=await import('./storage/notifications.js');
    const {JevRepository}=await import('./storage/jev.js');
    const store=f.service().store;
    const notices=new NotificationRepository(store),jev=new JevRepository(store);
    notices.put(NotificationViewSchema.parse({id:'evidence',source_id:'evidence',reason:'task_result',text:'合成完成',planned_at:1000,created_at:1000}));
    const value=JevDecisionSchema.parse({action:'quiet',reason:'合成判断',mode:'shadow',status:'decided',created_at:1000,not_before:1600});
    jev.reserve('evidence','',value,1,30,60000);
    assert.equal((await f.call('notification.list'))[0]!.decision!.reason,'合成判断');
    assert.equal(notices.get('evidence')!.decision,null,'Decision remains authoritative in its own repository');
    jev.finish('evidence',{...value,status:'stale',reason:'来源已变化'});
    assert.equal((await f.call('notification.list'))[0]!.decision!.reason,'来源已变化');
    await f.restart();
    assert.equal((await f.call('notification.list'))[0]!.decision!.status,'stale');
  }finally{await f.close();}
});

test('saved credential presence is independent from model readiness and other provider keys',async()=>{
  const root=await mkdtemp(join(tmpdir(),'lobuddy-credential-status-'));
  const service=await createApplicationService({kind:'connect',storage:{data:join(root,'data'),workspace:join(root,'workspace'),logs:join(root,'logs'),create:true},credentials:{llm_api_key:'synthetic',fish_api_key:'synthetic',typesafe_api_key:'synthetic'}},()=>{});
  try{
    const context={requestId:'status',signal:new AbortController().signal};
    const settings=await service.handlers['settings.get']!({},context);
    assert.deepEqual(settings.credentials,{llm_api_key:true,llm_multimodal_api_key:false,fish_api_key:true,typesafe_api_key:true});
    assert.equal((await service.handlers['service.health']!({},context)).model_configured,false);
    assert.doesNotMatch(JSON.stringify(settings),/synthetic/);
  }finally{await service.close();await rm(root,{recursive:true,force:true});}
});
