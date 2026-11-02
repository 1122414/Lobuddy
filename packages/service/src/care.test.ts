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
    advance: (seconds: number) => { now += seconds; },
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
    f.restart(); assert.equal(f.care.view().items.length,1); assert.deepEqual(f.care.admit(proposal,'one'),item);
    assert.equal(f.care.admit(proposal,'two'),undefined);
    assert.equal(f.care.get(item.id)?.next_at,Date.parse('2026-11-04T10:00:00+08:00') / 1000);
  } finally { await f.close(); }
});
test('quotes, hypotheses, third-party intentions, secrets, sensitive material and assistant claims cannot enter care', async () => {
  const f = await fixture(); try {
    const bad = ['如果我明天有面试','他说我明天有面试','朋友明天要面试','我准备面试，工资是秘密','我准备面试，最近在吃药','我准备面试，密码是abc','我明天有面试吗？','不要记我明天有面试'];
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
