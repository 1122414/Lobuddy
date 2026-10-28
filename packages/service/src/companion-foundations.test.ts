import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatSessionSchema, MemoryItemSchema, TurnStateSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { runtimeSettings } from './config/settings.js';
import { KnowledgeService } from './knowledge/service.js';
import { ProjectService } from './knowledge/projects.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { Companionship } from './companion/policy.js';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-companion-foundations-'));
  const data = join(root, 'data'), workspace = join(root, 'workspace'); await mkdir(workspace);
  const store = new Store(join(data, 'lobuddy.db'), { create: true });
  const settings = runtimeSettings({ data, workspace, logs: join(root, 'logs') });
  const knowledge = new KnowledgeService(store, () => settings); knowledge.bootstrap();
  new ChatRepository(store).saveSession(ChatSessionSchema.parse({ id: 'current' }));
  let now = 1800000000;
  const companion = new Companionship(store, () => now);
  const projects = new ProjectService(store, knowledge.relationship, new AbortController().signal, () => now);
  const dialogue = new CompanionDialogue(store, companion, knowledge.relationship, projects, {
    enabled: () => false, quiet: () => false, canReserve: () => false,
    enqueue: () => assert.fail('No background generation in foundation tests'),
    analyze: async () => { throw Error('No model expected'); },
  }, () => now);
  const state = TurnStateSchema.parse({ session_id: 'current', turn_id: 'turn', task_id: 'task', engine_id: 'engine',
    input_text: '', lane: 'foreground', status: 'running' });
  const context = (input_text: string) => knowledge.context({ ...state, input_text });
  const save = (id: string, content: string, extra: Record<string, unknown> = {}) => knowledge.gateway.saveAdmitted(
    MemoryItemSchema.parse({ id, memory_type: 'episodic_memory', content, ...extra }));
  return { store, settings, knowledge, state, dialogue, context, save, advance: (seconds: number) => { now += seconds; },
    close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}

test('short Chinese questions and keywords retrieve the same grounded episode with default profile context', async () => {
  const f = await fixture();
  try {
    f.save('starbridge', '星桥项目上次决定保留本地离线功能');
    for (const query of ['星桥', '星桥项目上次决定了什么', '还记得星桥的选择吗？']) {
      assert.match(f.context(query), /Relevant Past Memory[\s\S]*星桥项目上次决定保留本地离线功能/, query);
    }
    assert.doesNotMatch(f.context('白茶的味道怎么样'), /Relevant Past Memory/);
  } finally { await f.close(); }
});

test('episode admission filters private, expired and forgotten sources before the candidate limit', async () => {
  const f = await fixture();
  try {
    f.settings.memory_max_episodic_results = 1;
    f.save('private', '星桥 私有另一个会话', { scope: 'other-session', importance: 1 });
    f.save('project', '星桥 另一个项目', { scope: 'project:other', importance: 1 });
    f.save('expired', '星桥 过期信息', { expires_at: '2000-01-01T00:00:00Z', importance: 1 });
    f.knowledge.relationship.blockSource('forgotten-turn');
    f.save('forgotten', '星桥 遗忘信息', { source_message_id: 'forgotten-turn', importance: 1 });
    f.save('local', '星桥 本会话有效线索', { scope: 'current', importance: 0.8 });
    const context = f.context('星桥');
    assert.match(context, /本会话有效线索/);
    assert.doesNotMatch(context, /私有另一个会话|另一个项目|过期信息|遗忘信息/);
  } finally { await f.close(); }
});

test('episodic budget does not depend on utterance length or hot profile size and skips oversized candidates', async () => {
  const f = await fixture();
  try {
    f.settings.memory_prompt_budget_chars = 300;
    f.settings.memory_prompt_budget_percent = 0.2;
    f.save('large', '白茶' + '详情'.repeat(500), { importance: 1 });
    f.save('small', '白茶适合冷泡', { importance: 0.5 });
    f.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id: 'profile', memory_type: 'user_profile', content: '偏好'.repeat(200) }));
    assert.match(f.context('白茶'), /Relevant Past Memory[\s\S]*白茶适合冷泡/);
    assert.ok([...f.context('白茶').split('### Relevant Past Memory')[1]!].length + '### Relevant Past Memory'.length <= 60);
    assert.doesNotMatch(f.context('白茶'), /详情/);
    f.settings.memory_prompt_budget_percent = 0;
    assert.doesNotMatch(f.context('白茶'), /Relevant Past Memory/);
    f.settings.memory_prompt_budget_percent = 0.2; f.settings.memory_prompt_budget_chars = 20;
    assert.doesNotMatch(f.context('白茶'), /Relevant Past Memory/);
  } finally { await f.close(); }
});

test('vague follow-ups and query punctuation do not select arbitrary episodes', async () => {
  const f = await fixture();
  try {
    f.save('unrelated', '我们上次讨论了星桥项目的决定');
    for (const query of ['', '后来呢', '上次决定了什么', '%_', '" OR 1=1 --']) {
      assert.doesNotMatch(f.context(query), /Relevant Past Memory/, query);
    }
    f.save('react', 'React 方案保留离线读取');
    assert.match(f.context('上次 react 的方案是什么？'), /React 方案保留离线读取/);
  } finally { await f.close(); }
});

test('corrected and deleted episodes stop contributing after a knowledge service restart', async () => {
  const f = await fixture();
  try {
    f.save('change', '星桥先用云端存储');
    f.knowledge.saveMemory({ memory_id: 'change', memory_type: 'episodic_memory', title: '星桥', content: '星桥改为本地存储' }, 'correct');
    const restarted = new KnowledgeService(f.store, () => f.settings);
    assert.match(restarted.context({ ...f.state, input_text: '星桥怎么存' }), /改为本地存储/);
    assert.doesNotMatch(restarted.context({ ...f.state, input_text: '星桥怎么存' }), /先用云端存储/);
    restarted.deleteMemory('change');
    assert.doesNotMatch(new KnowledgeService(f.store, () => f.settings).context({ ...f.state, input_text: '星桥' }), /Relevant Past Memory/);
  } finally { await f.close(); }
});

test('explicit conversational clauses support surrounding context and common listening phrasing', async () => {
  const f = await fixture();
  try {
    for (const [index, input_text] of ['我今天有点累，先听我讲就好', '今天发生了不少事。请先听我说完。',
      '先听我讲一下，别一直追问了', '我现在很烦', '麻烦你先听我讲就行'].entries()) {
      const session_id = `listening-${index}`;
      f.dialogue.respond({ ...f.state, session_id, input_text });
      assert.equal(f.dialogue.state(session_id)?.mode, 'listening', input_text);
    }
    f.dialogue.respond({ ...f.state, input_text: '我今天有点累，先听我讲就好' });
    f.dialogue.respond({ ...f.state, input_text: '我说完了，现在帮我分析一下' });
    assert.equal(f.dialogue.state('current')?.mode, 'discussing');
    assert.equal(f.dialogue.state('unrelated'), undefined);
    f.advance(3601); assert.equal(f.dialogue.state('current'), undefined);
  } finally { await f.close(); }
});

test('natural temporary and persistent topic boundaries normalize polite endings and retain their lifetime', async () => {
  const f = await fixture();
  try {
    for (const input_text of ['今天不想聊工作', '我今天先不想谈工作的事了', '我有点累，今天先别提工作了，陪我待会儿',
      '请今天不要聊工作这个话题']) {
      f.dialogue.respond({ ...f.state, input_text });
      assert.equal(f.dialogue.blocked('项目进展', true), true, input_text);
      assert.equal(f.dialogue.boundaries().filter(b => b.active).length, 1);
      assert.equal(f.dialogue.boundaries().find(b => b.active)?.subject, '工作');
      for (const boundary of f.dialogue.boundaries()) f.dialogue.release(boundary.id);
    }
    f.dialogue.respond({ ...f.state, input_text: '今天不想聊工作' }); f.advance(86400);
    assert.equal(f.dialogue.blocked('项目进展', true), false);
    f.dialogue.respond({ ...f.state, input_text: '以后不要再提股票了' }); f.advance(86400 * 10);
    assert.equal(f.dialogue.blocked('股票行情'), true);
    const permanent = f.dialogue.boundaries().find(b => b.active)!;
    assert.equal(permanent.expires_at, null); f.dialogue.release(permanent.id);
    assert.equal(f.dialogue.blocked('股票行情'), false);
    for (const subject of ['酒吧', '知了']) {
      f.dialogue.respond({ ...f.state, input_text: `今天不想聊${subject}` });
      assert.ok(f.dialogue.boundaries().some(b => b.active && b.subject === subject));
    }
  } finally { await f.close(); }
});

test('reported, hypothetical, questioned or negated instructions do not create listening or quiet boundaries', async () => {
  const f = await fixture();
  try {
    for (const [index, input_text] of ['他说今天不想聊工作', '如果我说今天不想聊工作', '今天不想聊工作吗？',
      '她说先听我讲就好', '“我今天有点累，先听我讲就好”', '不需要先听我讲', '我并不是今天不想聊工作',
      '转述一下，今天不想聊工作', '举个例子，先听我说完'].entries()) {
      const session_id = `negative-${index}`;
      f.dialogue.respond({ ...f.state, session_id, input_text });
      assert.notEqual(f.dialogue.state(session_id)?.mode, 'listening', input_text);
      assert.deepEqual(f.dialogue.boundaries().filter(b => b.active), [], input_text);
    }
  } finally { await f.close(); }
});
