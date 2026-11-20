import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { ChatSessionSchema, ChatMessageSchema, ProjectCreateSchema, CareProposalSchema, CareUpdateSchema } from '@lobuddy/contracts';
import { careNextAt, careWindow } from '@lobuddy/domain';
import { Store, STORAGE_VERSION, inspectDatabase } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { KnowledgeService } from './knowledge/service.js';
import { runtimeSettings } from './config/settings.js';
import { ProjectService } from './knowledge/projects.js';
import { CareService } from './companion/care.js';
import { CareDelivery } from './companion/care-delivery.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { Companionship } from './companion/policy.js';
import { CompanionHandoffs } from './companion/handoff.js';
import { TurnStateSchema } from '@lobuddy/contracts';

const at = Date.parse('2026-11-02T10:00:00+08:00') / 1000;
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-care-')),data = join(root,'data'),workspace = join(root,'workspace'); await mkdir(workspace);
  let store = new Store(join(data,'lobuddy.db'),{create: true}),now = at;
  let knowledge = new KnowledgeService(store,() => runtimeSettings({data,workspace,logs: join(root,'logs')}));
  let projects = new ProjectService(store,knowledge.relationship,new AbortController().signal,() => now);
  let care = new CareService(store,knowledge,projects,() => now);
  const wire = () => { knowledge.gateway.onChange = () => care.reconcile(); knowledge.relationship.onInvalidate = () => care.reconcile(); };
  wire();
  new ChatRepository(store).saveSession(ChatSessionSchema.parse({id: 'one'}));
  new ChatRepository(store).saveSession(ChatSessionSchema.parse({id: 'two'}));
  const source = (id: string,text: string,role: 'user'|'assistant' = 'user',session = 'one') => {
    new ChatRepository(store).saveMessage(ChatMessageSchema.parse({id,session_id: session,role,content: text,created_at: '2026-11-02T10:00:00'}));
    return CareProposalSchema.parse({source_id: id,quote: text,subject: '面试'});
  };
  return {root,get store(){return store;},get care(){return care;},get knowledge(){return knowledge;},get projects(){return projects;},source,
    now: () => now,advance: (seconds: number) => { now += seconds; },
    restart: () => { store.close(); store = new Store(join(data,'lobuddy.db')); knowledge = new KnowledgeService(store,() => runtimeSettings({data,workspace,logs: join(root,'logs')}));
      projects = new ProjectService(store,knowledge.relationship,new AbortController().signal,() => now); care = new CareService(store,knowledge,projects,() => now); wire(); },
    close: async () => { store.close(); await rm(root,{recursive: true,force: true}); } };
}
test('care resolves supported dates from source time, preserves unknown duration and respects timezone windows', () => {
  const next = (text: string) => new Date(careNextAt(text,at,'Asia/Shanghai') * 1000).toISOString();
  assert.equal(next('我明天有面试'),'2026-11-04T02:00:00.000Z');
  assert.equal(next('我后天有考试'),'2026-11-05T02:00:00.000Z');
  assert.equal(next('我本周五有面试'),'2026-11-07T02:00:00.000Z');
  assert.equal(next('下周五下午3点再问我面试'),'2026-11-13T07:00:00.000Z');
  assert.equal(next('2026-11-06 15:30再找我聊面试'),'2026-11-06T07:30:00.000Z');
  assert.equal(next('我2026-11-06有面试，下周五再聊'),'2026-11-13T02:00:00.000Z');
  assert.equal(next('下周五再问我第2场面试'),'2026-11-13T02:00:00.000Z');
  assert.equal(next('我最近准备面试'),'2026-11-04T02:00:00.000Z');
  assert.equal(next('我2026-02-30有面试'),'2026-11-04T02:00:00.000Z');
  assert.equal(careWindow(at,'Asia/Shanghai',9,23),true);
  assert.equal(careWindow(at - 2 * 3600,'Asia/Shanghai',9,23),false);
  assert.equal(careWindow(at + 13 * 3600,'Asia/Shanghai',9,23),false);
});
test('ordinary first-person updates use the memory gateway, remain scoped and are idempotent across restart', async () => {
  const f = await fixture(); try {
    const proposal = f.source('message','我明天有面试，准备练习项目介绍。');
    const item = f.care.admit(proposal,'one')!; assert.ok(item);
    assert.equal(f.knowledge.repo.get(item.memory_id)?.source_message_id,'message');
    assert.equal(f.knowledge.repo.get(item.memory_id)?.scope,'one');
    assert.deepEqual(f.care.admit(proposal,'one'),item);
    assert.deepEqual(f.care.admit({...proposal,subject:'准备练习'},'one'),item,'re-analysis with another exact subject does not duplicate the same source');
    f.restart(); assert.equal(f.care.view().items.length,1); assert.deepEqual(f.care.admit(proposal,'one'),item);
    assert.equal(f.care.admit(proposal,'two'),undefined);
    assert.equal(f.care.get(item.id)?.next_at,Date.parse('2026-11-04T10:00:00+08:00') / 1000);
  } finally { await f.close(); }
});
test('source absolute time and captured timezone survive later timezone changes without reinterpreting a naive timestamp',async()=>{
  const f=await fixture();try{
    const proposal=f.source('source','我明天有面试'),instant=Date.parse('2026-11-03T04:30:00Z')/1000;
    f.advance(instant-f.now());f.store.run("UPDATE chat_message SET created_at='2026-11-02T23:30:00' WHERE id='source'");
    f.store.run('INSERT INTO app_settings VALUES(?,?,?)','care_clock:source',JSON.stringify({at:instant,timezone:'America/New_York'}),'2026-11-03T04:30:00Z');
    f.care.configure({...f.care.policy,timezone:'UTC'});
    const item=f.care.admit(proposal,'one')!;assert.equal(item.next_at,Date.parse('2026-11-04T15:00:00Z')/1000);
  }finally{await f.close();}
});
test('quotes, hypotheses, third-party intentions, secrets, sensitive material and assistant claims cannot enter care', async () => {
  const f = await fixture(); try {
    const bad = ['如果我明天有面试','他说我明天有面试','你说我明天有面试','朋友明天要面试','我准备面试，工资是秘密','我准备面试，最近在吃药','我准备面试，密码是abc','我明天有面试吗？','不要记我明天有面试'];
    for (const [i,text] of bad.entries()) assert.equal(f.care.admit(f.source(`bad${i}`,text),'one'),undefined,text);
    assert.equal(f.care.admit(f.source('assistant','我明天有面试','assistant'),'one'),undefined);
    const valid = f.source('user','我明天有面试');
    assert.equal(f.care.admit({...valid,quote: '我已经通过面试'},'one'),undefined);
    assert.equal(f.care.all().length,0); assert.equal(f.knowledge.repo.list('episodic_memory').length,0);
  } finally { await f.close(); }
});
test('care revisions reject stale writes and replay returns current state instead of reviving an old response', async () => {
  const f = await fixture(); try {
    const item = f.care.admit(f.source('user','我最近准备面试'),'one')!;
    const pause = CareUpdateSchema.parse({id: item.id,revision: item.revision,action: 'pause'});
    const paused = f.care.update(pause,'pause-request'); assert.equal(paused.status,'paused');
    assert.throws(() => f.care.update({...pause,action: 'resume'}),/已更新/);
    const closed = f.care.update({id: item.id,revision: paused.revision,action: 'close'},'close-request');
    assert.equal(f.care.update(pause,'pause-request').status,'closed');
    assert.throws(() => f.care.update({...pause,action:'resume'},'pause-request'),/不一致/);
    f.restart(); assert.equal(f.care.update(pause,'pause-request').status,closed.status);
  } finally { await f.close(); }
});
test('correction, forgetting, changed project membership and expiration invalidate care facts durably', async () => {
  for (const change of ['edit','forget','project','expire']) {
    const f = await fixture(); try {
      const item = f.care.admit(f.source('source','我最近准备面试'),'one')!;
      if (change === 'edit') f.store.run("UPDATE chat_message SET content='我已经结束这件事' WHERE id='source'");
      if (change === 'forget') f.knowledge.deleteMemory(item.memory_id);
      if (change === 'project') { const project = f.projects.repo.create('p',ProjectCreateSchema.parse({name: '其他项目'})); f.store.run('INSERT INTO project_session VALUES(?,?,1)','one',project.id); }
      if (change === 'expire') f.advance(15 * 86400);
      f.care.reconcile(); assert.equal(f.care.view().items.length,0); assert.equal(f.knowledge.repo.get(item.memory_id),undefined);
      assert.equal(f.care.get(item.id)?.title,'来源已失效'); f.restart(); assert.equal(f.care.view().items.length,0);
    } finally { await f.close(); }
  }
});
test('care preparation recovers a durable gateway fact and invalidates a preparation with no fact', async () => {
  const f = await fixture(); try {
    const item = f.care.admit(f.source('source','我最近准备面试'),'one')!;
    f.store.run('UPDATE companion_care SET body=? WHERE id=?',JSON.stringify({...item,status:'preparing'}),item.id);
    f.restart(); assert.equal(f.care.get(item.id)?.status,'active');
    f.store.run('DELETE FROM memory_item WHERE id=?',item.memory_id);
    f.store.run('UPDATE companion_care SET body=? WHERE id=?',JSON.stringify({...item,status:'preparing'}),item.id);
    f.restart(); assert.equal(f.care.get(item.id)?.status,'invalid');
  } finally { await f.close(); }
});
test('v4 care migration keeps prior fingerprints, verifies a private backup and rolls back a collision', async () => {
  for (const fail of [false,true]) {
    const f = await fixture(); try {
      const before = f.store.connection.prepare("SELECT * FROM ts_migration WHERE id!='003-continuous-care' ORDER BY id").all();
      const path = f.store.path; f.store.close(); const old = new DatabaseSync(path);
      old.exec("DROP TABLE companion_care; DROP TABLE companion_delivery; DROP TABLE companion_care_request; DELETE FROM ts_migration WHERE id='003-continuous-care'; PRAGMA user_version=4;");
      if (fail) old.exec('CREATE TABLE companion_care(id TEXT PRIMARY KEY, body TEXT)'); old.close();
      if (fail) {
        assert.throws(() => new Store(path),/already exists/); const unchanged = new DatabaseSync(path);
        try { assert.equal(inspectDatabase(unchanged).version,4); assert.equal(unchanged.prepare("SELECT 1 FROM sqlite_schema WHERE name='companion_delivery'").get(),undefined); } finally { unchanged.close(); }
      } else {
        const upgraded = new Store(path); try {
          assert.equal(inspectDatabase(upgraded.connection).version,STORAGE_VERSION);
          assert.deepEqual(upgraded.connection.prepare("SELECT * FROM ts_migration WHERE id!='003-continuous-care' ORDER BY id").all(),before);
          const snapshots = (await readdir(join(f.root,'data'))).filter(name => name.startsWith('pre-v5-')); assert.equal(snapshots.length,1);
          const backup = new DatabaseSync(join(f.root,'data',snapshots[0]!)); try { assert.equal(inspectDatabase(backup).version,4); } finally { backup.close(); }
        } finally { upgraded.close(); }
      }
    } finally { await f.close(); }
  }
});

async function deliveryFixture() {
  const f = await fixture(),companion = new Companionship(f.store,f.now),jobs: string[] = [];
  let quiet = false,calls = 0;
  const dialogue = new CompanionDialogue(f.store,companion,f.knowledge.relationship,f.projects,{
    enabled: () => true,quiet: () => quiet,canReserve: () => true,enqueue: (_kind,id) => jobs.push(id),
    analyze: async prompt => {
      calls++; if (prompt.startsWith('独立审查')) return JSON.stringify({choice:0,clauses:[{kind:'question',claim:'面试准备得怎么样了？',evidence:null}],grounded:true,natural:true,respectful:true});
      const candidate = dialogue.invitations.candidates()[0]!;
      return JSON.stringify({action:'speak',source_id:candidate.source_id,quote:'面试',text:'面试准备得怎么样了？'});
    },
  },f.now);
  const delivery = new CareDelivery(f.care,dialogue,companion,() => quiet),handoffs = new CompanionHandoffs(dialogue);
  f.care.onChange = () => {dialogue.clear();handoffs.reconcile();};
  return {...f,companion,dialogue,delivery,handoffs,restart:()=>{f.restart();return f.care;},calls:()=>calls,quiet:(value:boolean)=>{quiet=value;},
    show: async () => {
      delivery.poll();delivery.tick();dialogue.enqueue();assert.ok(jobs.length);await dialogue.prepare(jobs.at(-1)!);
      f.advance(31);delivery.poll();const notice=companion.poll(false,false);assert.ok(notice);return notice;
    },reply:(text:string)=>{
      const id=crypto.randomUUID();new ChatRepository(f.store).saveMessage(ChatMessageSchema.parse({id,session_id:'one',role:'user',content:text,created_at:new Date(f.now()*1000).toISOString()}));
      delivery.respond(TurnStateSchema.parse({session_id:'one',turn_id:id,task_id:id,engine_id:'fake',input_text:text,status:'running',lane:'foreground'}));return id;
    }};
}
test('due care generates without a return event, acknowledges actual display once and reconnects the originating session', async () => {
  const f=await deliveryFixture();try{
    const item=f.care.admit(f.source('source','我最近准备面试'),'one')!;f.advance(48*3600);
    f.delivery.tick();assert.equal(f.calls(),0);assert.equal(f.companion.state.pending,'','no visible pet lease means no model work');
    const notice=await f.show();assert.equal(notice.source,'care_due');assert.equal(f.calls(),2);assert.equal(f.companion.state.used,0);
    assert.equal(f.companion.presented(notice.notice_id),true);assert.equal(f.companion.presented(notice.notice_id),true);
    assert.equal(f.companion.state.used,1);assert.equal(f.care.get(item.id)?.unanswered,1);
    assert.equal(f.handoffs.accept(notice.notice_id,'two').session_id,'one');
    f.reply('还没开始');assert.equal(f.care.get(item.id)?.unanswered,0);assert.equal(f.care.get(item.id)?.status,'active');
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM companion_delivery').get()!.n,1);
  }finally{await f.close();}
});
test('delayed extraction preserves the original mention time in candidate and handoff material',async()=>{
  const f=await deliveryFixture();try{
    const proposal=f.source('source','我明天有面试');f.advance(48*3600);const item=f.care.admit(proposal,'one')!;
    const candidate=f.delivery.candidates()[0]!;assert.equal(candidate.created_at,at);assert.match(candidate.source_time!,/2026\/11\/2/);
    assert.equal(Date.parse(f.knowledge.repo.get(item.memory_id)!.created_at)/1000,at);
    assert.equal(f.dialogue.material(`care:${item.id}`)?.source_time,candidate.source_time);
  }finally{await f.close();}
});
test('two displayed unanswered invitations wait at least 48 hours and then pause; preparation never counts as delivery', async()=>{
  const f=await deliveryFixture();try{
    const item=f.care.admit(f.source('source','我最近准备面试'),'one')!;f.advance(48*3600);
    const first=await f.show();assert.equal(f.companion.presented(first.notice_id),true);
    f.advance(21);f.delivery.poll();f.companion.poll(false,false);assert.equal(f.care.get(item.id)?.unanswered,1);
    f.advance(47*3600);assert.equal(f.care.due().length,0);
    f.advance(3600);const second=await f.show();assert.equal(f.companion.presented(second.notice_id),true);
    f.advance(21);f.delivery.poll();f.companion.poll(false,false);assert.equal(f.care.get(item.id)?.status,'paused');
    assert.equal(f.care.get(item.id)?.unanswered,2);assert.equal(f.companion.state.used,1,'new local day resets only the global day count');
    const copy=f.care.get(item.id),restored=f.restart();assert.deepEqual(restored.get(item.id),copy);
  }finally{await f.close();}
});
test('busy state, source retirement, missing receipt and failed persistence cannot consume a display or produce a late invitation',async()=>{
  const f=await deliveryFixture();try{
    const item=f.care.admit(f.source('source','我最近准备面试'),'one')!;f.advance(48*3600);
    f.quiet(true);f.delivery.poll();f.delivery.tick();f.dialogue.enqueue();assert.equal(f.calls(),0);f.quiet(false);
    const notice=await f.show();f.delivery.hide();assert.equal(f.companion.presented(notice.notice_id),false);assert.equal(f.companion.state.used,0);
    assert.equal(f.care.get(item.id)?.unanswered,0);
    f.companion.state.pending='';f.advance(61);const retry=await f.show();
    const save=f.store.run.bind(f.store);f.store.run=(sql,...args)=>{if(sql.startsWith('INSERT INTO companion_delivery'))throw Error('injected storage failure');return save(sql,...args);};
    assert.throws(()=>f.companion.presented(retry.notice_id),/storage failure/);f.store.run=save;
    assert.equal(f.companion.state.used,0);assert.equal(f.care.get(item.id)?.unanswered,0);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM companion_delivery').get()!.n,0);
    f.knowledge.deleteMemory(item.memory_id);assert.equal(f.companion.presented(retry.notice_id),false);assert.equal(f.dialogue.choose(),undefined);
  }finally{await f.close();}
});
test('explicit replies change only the linked concern while navigation or ambiguous replies do not establish preference',async()=>{
  for(const [reply,status,delay] of [['没有新进展','deferred',7*86400],['暂时不聊','deferred',48*3600],['暂时不聊面试','deferred',48*3600],['面试结束了','closed',0],['结束了','closed',0],['别再问','paused',0],['下周五再聊','deferred',0]] as const){
    const f=await deliveryFixture();try{
      const item=f.care.admit(f.source('source','我最近准备面试'),'one')!;f.advance(48*3600);
      const notice=await f.show();f.companion.presented(notice.notice_id);f.handoffs.accept(notice.notice_id,'two');
      assert.equal(f.care.get(item.id)?.unanswered,1,'opening is not a reply');f.reply('嗯');assert.equal(f.care.get(item.id)?.unanswered,1);
      f.reply(reply);const next=f.care.get(item.id)!;assert.equal(next.status,status,reply);if(delay)assert.equal(next.next_at,f.now()+delay);
    }finally{await f.close();}
  }
});
test('explicitly resuming a dismissed care topic clears its topic block without resetting global quota',async()=>{
  const f=await deliveryFixture();try{
    const item=f.care.admit(f.source('source','我最近准备面试'),'one')!;f.advance(48*3600);
    const notice=await f.show();f.companion.presented(notice.notice_id);f.companion.feedback({notice_id:notice.notice_id,action:'never'});
    const paused=f.care.get(item.id)!;assert.equal(paused.status,'paused');
    assert.equal(f.store.connection.prepare('SELECT blocked FROM companion_topic WHERE id=?').get(`care:${item.id}`)!.blocked,1);
    f.care.update({id:item.id,revision:paused.revision,action:'resume'});
    assert.equal(f.store.connection.prepare('SELECT blocked FROM companion_topic WHERE id=?').get(`care:${item.id}`)!.blocked,0);
    assert.equal(f.companion.state.used,1);
  }finally{await f.close();}
});
test('a care model result arriving after hiding, pausing or forgetting cannot become a displayed invitation',async()=>{
  for(const change of ['hide','pause','forget']){
    const f=await deliveryFixture();try{
      const item=f.care.admit(f.source('source','我最近准备面试'),'one')!;f.advance(48*3600);f.delivery.poll();f.delivery.tick();f.dialogue.enqueue();
      const row=f.store.connection.prepare('SELECT id FROM dialogue_invitation').get()!;
      let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});
      f.dialogue.learning.analyze=async()=>{await held;return JSON.stringify({action:'speak',source_id:`care:${item.id}`,quote:'面试',text:'面试准备得怎么样了？'});};
      const pending=f.dialogue.prepare(String(row.id));
      if(change==='hide')f.delivery.hide();
      if(change==='pause')f.care.update({id:item.id,revision:item.revision,action:'pause'});
      if(change==='forget')f.knowledge.deleteMemory(item.memory_id);
      release();await pending;assert.equal(f.dialogue.choose(),undefined);assert.equal(f.companion.state.used,0);
    }finally{await f.close();}
  }
});
