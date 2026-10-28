import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatSessionSchema, ChatMessageSchema, MemoryItemSchema, TurnStateSchema, SourceShareSchema, ProjectCreateSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { runtimeSettings } from './config/settings.js';
import { KnowledgeService } from './knowledge/service.js';
import { MemoryWriteGateway } from './knowledge/gateway.js';
import { ProjectService } from './knowledge/projects.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { CompanionHandoffs } from './companion/handoff.js';
import { Companionship } from './companion/policy.js';

async function fixture() {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'lobuddy-handoff-')));
  const data = join(root, 'data'), workspace = join(root, 'workspace'); await mkdir(workspace);
  const store = new Store(join(data, 'lobuddy.db'), { create: true });
  const settings = runtimeSettings({ data, workspace, logs: join(root, 'logs') });
  const knowledge = new KnowledgeService(store, () => settings); knowledge.bootstrap();
  const chat = new ChatRepository(store);
  for (const id of ['one','two']) chat.saveSession(ChatSessionSchema.parse({ id }));
  let now = Date.now() / 1000, busy = '';
  const companion = new Companionship(store, () => now);
  const projects = new ProjectService(store, knowledge.relationship, new AbortController().signal, () => now);
  const dialogue = new CompanionDialogue(store, companion, knowledge.relationship, projects, {
    enabled: () => false, quiet: () => false, canReserve: () => false, enqueue: () => {}, analyze: async () => '' }, () => now);
  const handoffs = new CompanionHandoffs(dialogue, id => id === busy);
  knowledge.gateway.onChange = () => handoffs.reconcile();
  knowledge.relationship.onInvalidate = () => { dialogue.clear(); store.run('DELETE FROM engine_session'); handoffs.reconcile(); };
  knowledge.dialogueContext = state => handoffs.context(state) + dialogue.context(state);
  const state = (session_id: string, turn_id = 'turn') => TurnStateSchema.parse({ session_id, turn_id, task_id: turn_id,
    engine_id: 'engine', input_text: '后来呢？', lane: 'foreground', status: 'running' });
  const save = (id = 'memory', content = '星桥上次决定保留离线功能', extra = {}) => knowledge.gateway.saveAdmitted(
    MemoryItemSchema.parse({ id, memory_type: 'episodic_memory', content, ...extra }));
  const show = (sourceId = 'memory', id = 'notice') => {
    const source = dialogue.source(sourceId); assert.ok(source);
    companion.topics.shown({ topic_id: source.topic, memory_id: sourceId, revision: source.revision, text: '' });
    const notice = { notice_id: id, text: '想到你之前说的「星桥」。想接着聊时，我在。', source: 'app_returned',
      expires_at: now + 20, memory_id: sourceId, topic_id: source.topic };
    companion.state.notice = notice; companion.save(); return notice;
  };
  const project = (id: string) => projects.repo.create(id, ProjectCreateSchema.parse({ name: id }));
  const share = (project_id: string, extra = {}) => projects.share(crypto.randomUUID(), SourceShareSchema.parse({ project_id,
    title: '星桥', category: 'recent', expires_at: now + 86400, text: '星桥决定保留离线功能', ...extra }));
  return { root, store, chat, knowledge, companion, dialogue, handoffs, projects, save, show, project, share, state,
    advance: (seconds: number) => { now += seconds; }, busy: (id: string) => { busy = id; },
    close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}

test('explicit click transfers one assistant utterance and source, persists after restart, and stays in its session', async () => {
  const f = await fixture();
  try {
    f.save(); const notice = f.show();
    assert.equal(f.handoffs.context(f.state('one')), '', 'display is not acceptance');
    const first = f.handoffs.accept(notice.notice_id, 'one');
    assert.equal(first.session_id, 'one');
    assert.deepEqual(f.handoffs.accept(notice.notice_id, 'two'), first);
    assert.equal(f.chat.messages('one').length, 1);
    assert.equal(f.chat.messages('one')[0]!.role, 'assistant');
    assert.equal(f.chat.messages('one')[0]!.content, notice.text);
    for (let n = 0; n < 3; n++) assert.match(f.knowledge.context(f.state('one', `t${n}`)), /星桥上次决定保留离线功能/);
    assert.equal(f.handoffs.context(f.state('two')), '');
    const path = f.store.path; f.store.close();
    const reopened = new Store(path);
    try {
      const policy = new Companionship(reopened);
      const knowledge = new KnowledgeService(reopened, f.knowledge.settings);
      const projects = new ProjectService(reopened, knowledge.relationship, new AbortController().signal);
      const dialogue = new CompanionDialogue(reopened, policy, knowledge.relationship, projects, f.dialogue.learning);
      const handoffs = new CompanionHandoffs(dialogue);
      assert.deepEqual(handoffs.accept('notice', 'two'), first);
      assert.match(handoffs.context(f.state('one')), /星桥上次决定保留离线功能/);
      assert.equal(new ChatRepository(reopened).messages('one').length, 1);
    } finally { reopened.close(); }
  } finally { await f.close(); }
});

test('project topics route to their own scope and never inject into a busy conversation', async () => {
  const f = await fixture();
  try {
    const one = f.project('one'), two = f.project('two');
    f.projects.repo.bind('one', one.id, 0); f.projects.repo.bind('two', two.id, 0);
    const source = await f.share(one.id); f.show(`project:${source.id}`);
    const accepted = f.handoffs.accept('notice','two');
    assert.notEqual(accepted.session_id, 'two');
    assert.equal(f.projects.repo.selection(accepted.session_id).project_id, one.id);
    assert.equal(f.chat.messages('two').length, 0);
    assert.equal(f.handoffs.context(f.state('two')), '');
    assert.match(f.handoffs.context(f.state(accepted.session_id)), /星桥决定/);
    assert.equal(f.handoffs.context({ ...f.state(accepted.session_id), project_id: two.id }), '');
    f.show(`project:${source.id}`, 'again'); f.busy('one');
    assert.notEqual(f.handoffs.accept('again','one').session_id, 'one');
    f.projects.repo.bind(accepted.session_id, two.id, 1); f.handoffs.reconcile();
    assert.throws(() => f.handoffs.accept('notice'), /撤回/);
    assert.equal(f.chat.messages(accepted.session_id).length, 0);
  } finally { await f.close(); }
});

test('revoked, forged, expired, quiet and source-changed notices never become history', async () => {
  const f = await fixture();
  try {
    f.save(); f.show(); assert.throws(() => f.handoffs.accept('forged'));
    f.advance(21); assert.throws(() => f.handoffs.accept('notice')); assert.equal(f.chat.messages('one').length, 0);
    f.show(); f.companion.policy.do_not_disturb = true; assert.throws(() => f.handoffs.accept('notice'));
    f.companion.policy.do_not_disturb = false;
    f.save('memory', '星桥改为本地存档'); assert.throws(() => f.handoffs.accept('notice'));
    f.show(); f.dialogue.respond({ ...f.state('one'), input_text: '今天不想聊星桥' });
    assert.throws(() => f.handoffs.accept('notice')); assert.equal(f.chat.messages('one').length, 0);
  } finally { await f.close(); }
});

test('memory correction removes handed-off history, summaries, derived memories and engine associations', async () => {
  const f = await fixture();
  try {
    f.save(); f.show(); f.handoffs.accept('notice', 'one');
    f.handoffs.context(f.state('one'));
    f.chat.saveMessage(ChatMessageSchema.parse({ id: 'turn', session_id: 'one', role: 'user', content: '星桥还是离线吧' }));
    f.save('derived', '星桥过时的派生结论', { source_message_id: 'turn-reply' });
    f.store.run("INSERT INTO engine_session VALUES('one','foreground','old-engine',0)");
    f.save('unrelated', '白茶的味道清淡');
    assert.equal(f.chat.messages('one').length, 2, 'unrelated writes retain valid handoff');
    f.knowledge.saveMemory({ memory_id: 'memory', memory_type: 'episodic_memory', title: '星桥', content: '星桥改为联网同步' }, 'correction');
    assert.equal(f.handoffs.context(f.state('one')), '');
    assert.throws(() => f.handoffs.accept('notice'), /撤回/);
    assert.equal(f.chat.messages('one').filter(m => m.role === 'assistant').length, 0);
    assert.equal(f.knowledge.repo.get('derived'), undefined);
    assert.equal(f.store.connection.prepare('SELECT * FROM engine_session').all().length, 0);
    assert.equal(f.knowledge.relationship.sources(['turn']).length, 0);
    assert.equal(f.knowledge.search.search('星桥','one','all_sessions').results.length, 0);
  } finally { await f.close(); }
});

test('expiry, deletion and source-message barriers retire accepted memory topics', async () => {
  for (const reason of ['expiry','delete','barrier'] as const) {
    const f = await fixture();
    try {
      f.save('memory', '星桥上次决定保留离线功能', reason === 'expiry' ? { expires_at: new Date(Date.now() + 40000).toISOString() } : { source_message_id: 'origin' });
      f.show(); f.handoffs.accept('notice','one'); f.handoffs.context(f.state('one'));
      if (reason === 'expiry') f.advance(41);
      if (reason === 'delete') f.knowledge.deleteMemory('memory');
      if (reason === 'barrier') f.knowledge.relationship.blockSource('origin');
      assert.equal(f.handoffs.context(f.state('one')), '', reason);
      assert.throws(() => f.handoffs.accept('notice'), /撤回/, reason);
      assert.equal(f.chat.messages('one').length, 0, reason);
    } finally { await f.close(); }
  }
});

test('project correction, forgetting, expiry and changed files invalidate accepted provenance', async () => {
  for (const reason of ['correction','forget','expiry','file'] as const) {
    const f = await fixture();
    try {
      const project = f.project('one'); f.projects.repo.bind('one',project.id,0);
      const file = join(f.root,'source.txt'); await writeFile(file, '星桥决定保留离线功能');
      const source = await f.share(project.id, reason === 'file' ? { kind: 'file', locator: file, text: '' } : reason === 'expiry' ? { expires_at: f.dialogue.clock() + 30 } : {});
      f.show(`project:${source.id}`); f.handoffs.accept('notice','one'); f.handoffs.context(f.state('one'));
      if (reason === 'correction') f.projects.invalidate(f.projects.repo.saveSource({ ...source, text: '星桥新决定' },source.revision));
      if (reason === 'forget') f.projects.forget(source);
      if (reason === 'expiry') f.advance(31);
      if (reason === 'file') await writeFile(file, '已经更新');
      assert.equal(f.handoffs.context(f.state('one')), '', reason);
      assert.throws(() => f.handoffs.accept('notice'), /撤回/, reason);
      assert.equal(f.chat.messages('one').length, 0, reason);
    } finally { await f.close(); }
  }
});

test('acceptance transaction rolls back completely and interrupted revocation resumes', async () => {
  const f = await fixture();
  try {
    f.save(); f.show();
    f.store.connection.exec("CREATE TRIGGER fail_accept BEFORE INSERT ON companion_handoff BEGIN SELECT RAISE(ABORT,'fault'); END");
    assert.throws(() => f.handoffs.accept('notice'), /fault/);
    assert.equal(f.chat.sessions().length, 2); assert.equal(f.chat.messages('one').length, 0);
    assert.ok(f.companion.state.notice);
    f.store.connection.exec('DROP TRIGGER fail_accept');
    f.handoffs.accept('notice','one');
    f.store.run("UPDATE companion_handoff SET status='revoking'");
    new CompanionHandoffs(f.dialogue).reconcile();
    assert.equal(f.store.connection.prepare('SELECT status FROM companion_handoff').get()!.status,'revoked');
    assert.equal(f.chat.messages('one').length,0);
  } finally { await f.close(); }
});

test('a failed derived-file refresh cannot leave the old handed-off source authoritative', async () => {
  const f = await fixture();
  try {
    f.save(); f.show(); f.handoffs.accept('notice','one');
    const gateway = new MemoryWriteGateway(f.knowledge.repo, () => { throw Error('projection unavailable'); });
    gateway.onChange = () => f.handoffs.reconcile();
    assert.throws(() => gateway.saveManual(MemoryItemSchema.parse({ ...f.knowledge.repo.get('memory'), content: '星桥已修改' })), /projection unavailable/);
    assert.equal(f.store.connection.prepare('SELECT status FROM companion_handoff').get()!.status,'revoked');
    assert.equal(f.chat.messages('one').length,0);
  } finally { await f.close(); }
});
