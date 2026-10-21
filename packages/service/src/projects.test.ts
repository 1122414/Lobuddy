import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, rm, writeFile, symlink, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatSessionSchema, SourceShareSchema, TurnStateSchema, ProjectCreateSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { ProjectService } from './knowledge/projects.js';
import { KnowledgeService } from './knowledge/service.js';
import { runtimeSettings } from './config/settings.js';
import { sourceFingerprint } from './storage/projects.js';
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-project-ts-')); await mkdir(join(root,'workspace'));
  const store = new Store(join(root,'data/lobuddy.db'), { create: true });
  const chat = new ChatRepository(store); chat.saveSession(ChatSessionSchema.parse({ id: 's', title: '项目对话' }));
  const settings = runtimeSettings({ data: join(root,'data'), workspace: join(root,'workspace'), logs: join(root,'logs') });
  const knowledge = new KnowledgeService(store,() => settings), projects = new ProjectService(store,knowledge.relationship,new AbortController().signal);
  knowledge.projectContext = state => projects.context(state);
  const project = projects.repo.create('create',ProjectCreateSchema.parse({ name: '同名项目', goal: '完成材料' }));
  return { root, store, chat, knowledge, projects, project,
    state: (projectId = project.id) => TurnStateSchema.parse({ turn_id: 'turn', task_id: 'task', engine_id: 'engine', session_id: 's', project_id: projectId, input_text: '目前进度', lane: 'foreground', status: 'running' }),
    share: (text: string, changes = {}) => SourceShareSchema.parse({ title: '近况材料', text, project_id: project.id, ...changes }),
    close: async () => { store.close(); await rm(root,{ recursive: true, force: true }); } };
}
test('project request identity returns current state and revisions prevent stale edits', async () => {
  const f = await fixture();
  try {
    const changed = f.projects.repo.saveProject({ ...f.project, goal: '修改目标' },1);
    assert.equal(f.projects.repo.create('create',ProjectCreateSchema.parse({ name: '同名项目', goal: '完成材料' })).goal,'修改目标');
    assert.throws(() => f.projects.repo.create('create',{ name: '另一份', goal: '' }), /不一致/);
    assert.throws(() => f.projects.repo.saveProject(f.project,1), /已更新/);
    assert.equal(changed.id,f.project.id); assert.equal(changed.revision,2);
    f.projects.repo.bind('s',f.project.id,0); assert.throws(() => f.projects.repo.bind('s','',0), /已变化/);
    f.projects.repo.bind('s','',1); assert.equal(f.projects.repo.selection('s').project_id,'');
  } finally { await f.close(); }
});
test('same-name projects remain isolated, forgetting tombstones replay responses and invalidates recorded use', async () => {
  const f = await fixture();
  try {
    const second = f.projects.repo.create('second',ProjectCreateSchema.parse({ name: '同名项目' }));
    const source = await f.projects.share('share',f.share('第一个项目决定先准备蓝图'));
    assert.match(f.knowledge.context(f.state()), /先准备蓝图/);
    assert.doesNotMatch(f.knowledge.context(f.state(second.id)), /先准备蓝图/);
    assert.deepEqual(f.projects.repo.sourceTurns(source.id),['turn']);
    f.projects.forget(source);
    const replay = await f.projects.share('share',f.share('第一个项目决定先准备蓝图'));
    assert.equal(replay.status,'forgotten'); assert.equal(replay.text,''); assert.equal(replay.locator,'');
    assert.doesNotMatch(f.knowledge.context(f.state()), /先准备蓝图/);
    assert.throws(() => f.projects.repo.saveSource(source,1), /遗忘/);
    assert.ok(f.store.connection.prepare('SELECT 1 FROM relationship_barrier WHERE source_id=?').get('turn'));
  } finally { await f.close(); }
});
test('selected text sources detect changed, missing, symlink and expired files without accepting stale quotations', async () => {
  const f = await fixture();
  try {
    const path = join(await realpath(f.root),'notes.txt'); await writeFile(path,'资料原文');
    const spec = f.share('',{ kind: 'file', locator: path });
    const source = await f.projects.share('file',spec); assert.equal(source.text,'资料原文');
    await writeFile(path,'改变后的资料'); assert.equal(f.projects.fresh(source).status,'changed');
    const latest = await f.projects.share('file-new',spec); await rm(path);
    assert.equal(f.projects.fresh(latest).status,'missing');
    await writeFile(join(f.root,'other.txt'),'另一份'); await symlink(join(f.root,'other.txt'),path);
    await assert.rejects(f.projects.share('link',spec), /不可读取/);
    const expires = await f.projects.share('expiry',f.share('一次性资料',{ expires_at: Date.now() / 1000 + 60 }));
    const future = new ProjectService(f.store,f.knowledge.relationship,new AbortController().signal,() => Date.now() / 1000 + 120);
    assert.equal(future.fresh(expires).status,'expired');
  } finally { await f.close(); }
});
test('source fingerprint preserves the legacy float spelling for integral expiry timestamps', () => {
  const spec = SourceShareSchema.parse({ title: '资料', text: '原文', session_id: 's', expires_at: 1800000000 });
  const legacy = '{"kind":"text","category":"material","title":"资料","text":"原文","locator":"","project_id":"","session_id":"s","source_message_id":"","expires_at":1800000000.0,"sensitive_confirmed":false}';
  assert.equal(sourceFingerprint(spec),createHash('sha256').update(legacy).digest('hex'));
});
