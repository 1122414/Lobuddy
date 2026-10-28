import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, readFile, writeFile, readdir, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MemoryItemSchema, ChatSessionSchema, ChatMessageSchema, TurnStateSchema, ConversationSummarySchema, MemoryArgumentsSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { KnowledgeService } from './knowledge/service.js';
import { runtimeSettings } from './config/settings.js';
import { Approvals } from './tasks/approvals.js';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-knowledge-')), data = join(root, 'data'), workspace = join(root, 'workspace');
  await mkdir(workspace); const store = new Store(join(data, 'lobuddy.db'), { create: true });
  const settings = runtimeSettings({ data, workspace, logs: join(root, 'logs') });
  const knowledge = new KnowledgeService(store, () => settings), chat = new ChatRepository(store);
  chat.saveSession(ChatSessionSchema.parse({ id: 's' }));
  chat.saveMessage(ChatMessageSchema.parse({ id: 't', session_id: 's', role: 'user', content: '请保存项目选择，稍后我确认' }));
  const state = TurnStateSchema.parse({ session_id: 's', turn_id: 't', task_id: 'task', engine_id: 'e', input_text: '请保存项目选择，稍后我确认', lane: 'foreground', status: 'running' });
  return { root, workspace, store, settings, knowledge, chat, state, close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}
test('bootstrap profiles retain IDs, skip empty user names and update only changed values', async () => {
  const f = await fixture();
  try {
    f.settings.pet_name = 'TestPet'; f.settings.user_name = ''; f.knowledge.bootstrap();
    assert.equal(f.knowledge.repo.list('user_profile').length, 0);
    const pet = f.knowledge.repo.list('system_profile')[0]!;
    assert.match(pet.content, /TestPet/); assert.equal(pet.source, 'bootstrap');
    f.settings.user_name = 'Alice'; f.knowledge.bootstrap();
    const user = f.knowledge.repo.list('user_profile')[0]!; assert.match(user.content, /Alice/);
    f.knowledge.bootstrap(); assert.deepEqual(f.knowledge.repo.get(user.id), user); assert.deepEqual(f.knowledge.repo.get(pet.id), pet);
    f.settings.pet_name = 'NewPet'; f.settings.user_name = 'Bob'; f.knowledge.bootstrap();
    assert.match(f.knowledge.repo.get(pet.id)!.content, /NewPet/); assert.match(f.knowledge.repo.get(user.id)!.content, /Bob/);
    assert.doesNotMatch(f.knowledge.repo.get(user.id)!.content, /Alice/);
    f.settings.user_name = ''; f.knowledge.bootstrap();
    assert.equal(f.knowledge.repo.list('user_profile', 'active').length, 0); assert.equal(f.knowledge.repo.get(user.id)!.status, 'deprecated');
    assert.doesNotMatch(await readFile(join(f.workspace, 'USER.md'), 'utf8'), /Alice|Bob/);
  } finally { await f.close(); }
});
test('legacy profile import backs up before projection, rolls back partial admission and never revives forgotten rows', async () => {
  const f = await fixture(), directory = join(f.settings.data_dir,'memory'), path = join(directory,'USER.md');
  try {
    await mkdir(directory,{ recursive: true });
    const source = '# User\n\n## Basic Notes\n- 喜欢台湾口音\n- email user@example.com\n';
    await writeFile(path,source);
    f.store.connection.exec("CREATE TRIGGER fail_second_import BEFORE INSERT ON memory_item WHEN NEW.content LIKE 'email %' BEGIN SELECT RAISE(ABORT, 'injected database failure'); END");
    assert.throws(() => f.knowledge.bootstrap(),/injected database failure/);
    assert.equal(f.knowledge.repo.list('user_profile').length,0);
    assert.equal(await readFile(path,'utf8'),source);
    const backups = (await readdir(directory)).filter(value => value.endsWith('.bak'));
    assert.equal(backups.length,1); assert.equal(await readFile(join(directory,backups[0]!),'utf8'),source);
    f.store.connection.exec('DROP TRIGGER fail_second_import');
    f.knowledge.bootstrap();
    const records = f.knowledge.repo.list('user_profile'); assert.equal(records.length,2);
    assert.ok(records.every(item => item.source === 'migration' && item.confidence === 0.9 && item.priority === 70));
    assert.doesNotMatch(JSON.stringify(records),/user@example.com/);
    assert.match(f.knowledge.context({ ...f.state, session_id: 'other' }),/喜欢台湾口音/);
    new KnowledgeService(f.store,() => f.settings).bootstrap();
    assert.deepEqual(f.knowledge.repo.list('user_profile'),records);
    for (const item of records) f.knowledge.deleteMemory(item.id);
    await writeFile(path,source);
    new KnowledgeService(f.store,() => f.settings).bootstrap();
    assert.equal(f.knowledge.repo.list('user_profile').length,0);
  } finally { await f.close(); }
});
test('legacy import respects its switch and SQLite authority, rejects unsafe sources and deprecates invalid identities', async () => {
  const f = await fixture(), directory = join(f.settings.data_dir,'memory'), path = join(directory,'USER.md');
  try {
    await mkdir(directory,{ recursive: true }); await writeFile(path,'## Notes\n- 旧偏好\n');
    f.settings.memory_enable_migration = false; f.knowledge.bootstrap();
    assert.equal(f.knowledge.repo.list('user_profile').length,0); assert.match(await readFile(path,'utf8'),/旧偏好/);
    f.settings.memory_enable_migration = true;
    await rm(path); await symlink(join(f.workspace,'outside.md'),path); await writeFile(join(f.workspace,'outside.md'),'## Notes\n- 外部内容\n');
    assert.throws(() => f.knowledge.bootstrap(),/文件/);
    assert.equal(f.knowledge.repo.list('user_profile').length,0);
    await rm(path); await writeFile(path,'<!-- Generated by Lobuddy MemoryService -->\n## Notes\n- 已遗忘的投影\n');
    f.knowledge.bootstrap(); assert.equal(f.knowledge.repo.list('user_profile').length,0);
    for (const [id,type,content] of [['bad-user','user_profile',"The user's name is 谁."],['bad-pet','system_profile','My name is what.'],['valid','user_profile','喜欢 Who 乐队']] as const) {
      f.knowledge.repo.save(MemoryItemSchema.parse({ id, memory_type: type, content, source: 'migration' }));
    }
    f.knowledge.bootstrap();
    assert.equal(f.knowledge.repo.get('bad-user')!.status,'deprecated'); assert.equal(f.knowledge.repo.get('bad-pet')!.status,'deprecated');
    assert.equal(f.knowledge.repo.get('valid')!.status,'active');
    assert.doesNotMatch(f.knowledge.context(f.state),/name is 谁|name is what|已遗忘/);
    f.knowledge.prepare({ ...f.state, input_text: '你叫什么？' });
    assert.equal(f.knowledge.repo.list('system_profile','active').filter(item => item.source === 'strong_signal').length,0);
  } finally { await f.close(); }
});
test('manual correction preserves existing identity and provenance, invalidates summaries and erases all projections on deletion', async () => {
  const f = await fixture();
  try {
    const old = f.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id: 'old-id', memory_type: 'user_profile', content: '茉莉花茶', source_message_id: 'old-message', source_session_id: 'old-session' }));
    f.knowledge.gateway.saveSummary(ConversationSummarySchema.parse({ id: 'summary', session_id: 's', summary_type: 'semantic',
      content: JSON.stringify([{ kind: 'decision', content: 'outdated-name', source_ids: ['t'] }]) }));
    assert.match(f.knowledge.context(f.state), /茉莉花茶/);
    const saved = f.knowledge.saveMemory({ memory_id: old.id, memory_type: 'user_profile', title: '茶', content: '白桃乌龙茶' }, 'edit');
    assert.equal(saved.id, old.id); assert.equal(saved.source, 'manual'); assert.equal(saved.source_message_id, 'old-message');
    assert.equal(saved.source_session_id, 'old-session'); assert.equal(saved.confidence, 1);
    assert.match(f.knowledge.context({ ...f.state, session_id: 'other' }), /白桃乌龙茶/);
    assert.doesNotMatch(f.knowledge.context(f.state), /茉莉花茶|outdated-name/);
    assert.equal(f.knowledge.repo.summaries('s')[0]!.id, 'summary');
    await f.knowledge.relationship.analyze('s', async prompt => {
      assert.doesNotMatch(prompt, /outdated-name/);
      return JSON.stringify({ memories: [], summary: [] });
    });
    assert.equal(f.knowledge.deleteMemory(old.id), true);
    assert.equal(f.knowledge.deleteMemory(old.id), false);
    for (const path of [join(f.workspace, 'USER.md'), join(f.settings.data_dir, 'memory/USER.md')]) assert.doesNotMatch(await readFile(path, 'utf8'), /白桃乌龙茶/);
    assert.equal(new KnowledgeService(f.store, () => f.settings).repo.get(old.id), undefined);
    const safe = f.knowledge.saveMemory({ memory_id: null, memory_type: 'user_profile', title: 'safe', content: 'Token sk-abcdefghijklmnopqrstuvwxyz123456 user@example.com' }, 'safe');
    assert.doesNotMatch(JSON.stringify(safe), /sk-abcdefghijklmnopqrstuvwxyz123456|user@example.com/);
  } finally { await f.close(); }
});
test('approved memory tools preserve provenance and confidence; denial, cancellation, expiry and missing sources never write', async () => {
  const f = await fixture();
  let approvals: Approvals;
  let decision = false, active = true, revoke = false, emitError = false;
  approvals = new Approvals((_state, _kind, data) => {
    if (emitError) throw Error('delivery failed');
    queueMicrotask(() => { if (revoke) active = false; approvals.resolve(data.approval_id!, decision); if (!active) approvals.deny(); });
  });
  const tools = f.knowledge.tools(approvals), signal = new AbortController().signal;
  const request = (content: string, confidence = 0.95) => ({ callId: content, name: 'lobuddy_memory_propose' as const,
    arguments: MemoryArgumentsSchema.parse({ memory_type: 'project_memory', title: 'Choice', content, confidence }) });
  try {
    await assert.rejects(tools(request('denied'), f.state, signal, () => active));
    decision = true; revoke = true; await assert.rejects(tools(request('revoked'), f.state, signal, () => active));
    active = true; revoke = false; emitError = true; await assert.rejects(tools(request('no delivery'), f.state, signal, () => active));
    emitError = false;
    const abort = new AbortController(); abort.abort(); await assert.rejects(tools(request('cancelled'), f.state, abort.signal, () => active));
    assert.deepEqual(f.knowledge.repo.list('project_memory'), []);
    const result = JSON.parse(await tools(request('Use SQLite for project'), f.state, signal, () => active));
    assert.equal(result.accepted.length, 1); const item = result.accepted[0];
    assert.equal(item.source, 'ai_patch'); assert.equal(item.source_session_id, 's'); assert.equal(item.source_message_id, 't');
    assert.equal(item.confidence, 0.95); assert.deepEqual(f.knowledge.repo.get(item.id), item);
    f.settings.memory_gateway_min_confidence = 0.9;
    const review = JSON.parse(await tools(request('Uncertain project choice', 0.8), f.state, signal, () => active));
    assert.deepEqual(review.accepted, []); assert.equal(review.needs_review[0].status, 'needs_review');
    assert.doesNotMatch(f.knowledge.context(f.state), /Uncertain project choice/);
    assert.equal(f.knowledge.repo.list('project_memory').length, 2);
    f.settings.memory_gateway_min_confidence = 0.5; f.settings.memory_min_confidence = 0.95;
    const independent = JSON.parse(await tools(request('Independent admission threshold',0.7),f.state,signal,() => active));
    assert.equal(independent.accepted[0].confidence,0.7); assert.equal(independent.accepted[0].status,'active');
    const empty = JSON.parse(await tools(request('   '),f.state,signal,() => active));
    assert.equal(empty.rejected[0].reason,'empty_content');
    f.knowledge.relationship.blockSource('t');
    await assert.rejects(tools(request('stale source'), f.state, signal, () => active), /来源已失效/);
    assert.equal(f.knowledge.repo.list('project_memory').length, 0); assert.deepEqual(approvals.list(), []);
  } finally { approvals.deny(); await f.close(); }
});
test('ordinary explicit memory tools save exact evidence without a second approval', async () => {
  const f = await fixture(); let requested = 0;
  try {
    const text = '我喜欢白茶'; f.chat.saveMessage(ChatMessageSchema.parse({ id: 't', session_id: 's', role: 'user', content: text }));
    const tools = f.knowledge.tools(new Approvals(() => { requested++; throw Error('must not ask twice'); }));
    const request = { callId: 'remember', name: 'lobuddy_memory_propose' as const, arguments: MemoryArgumentsSchema.parse({ memory_type: 'user_profile', title: '茶', content: '喜欢白茶', confidence: 0.95 }) };
    const first = JSON.parse(await tools(request,{ ...f.state, input_text: text },new AbortController().signal,() => true));
    const again = JSON.parse(await tools(request,{ ...f.state, input_text: text },new AbortController().signal,() => true));
    assert.equal(first.id,again.id); assert.equal(first.content,text); assert.equal(first.status,'active'); assert.equal(requested,0);
    assert.equal(f.knowledge.repo.get(first.id)!.source_message_id,'t');
  } finally { await f.close(); }
});
test('episodic recall applies character and proportional caps independently of utterance and profile size', async () => {
  const f = await fixture();
  try {
    const query = 'React';
    f.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id: 'recall', memory_type: 'episodic_memory', content: 'Used React before' }));
    f.settings.memory_prompt_budget_chars = 100; f.settings.memory_prompt_budget_percent = 0.1;
    assert.doesNotMatch(f.knowledge.context({ ...f.state, input_text: query }),/Relevant Past Memory/);
    f.settings.memory_prompt_budget_percent = 1;
    assert.match(f.knowledge.context({ ...f.state, input_text: query }),/Relevant Past Memory/);
    f.settings.memory_prompt_budget_chars = 20;
    assert.doesNotMatch(f.knowledge.context({ ...f.state, input_text: query }),/Relevant Past Memory/);
    f.settings.memory_prompt_budget_chars = 100;
    f.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id: 'fixed', memory_type: 'user_profile', content: 'x'.repeat(80) }));
    assert.match(f.knowledge.context({ ...f.state, input_text: query }),/Relevant Past Memory/);
    f.settings.memory_prompt_budget_percent = 0;
    assert.doesNotMatch(f.knowledge.context({ ...f.state, input_text: query }),/Relevant Past Memory/);
  } finally { await f.close(); }
});

test('manual expression correction supersedes automatic preferences and deleted focus experiences never reappear', async () => {
  const f = await fixture();
  try {
    const content = '以后回答简短一点';
    f.chat.saveMessage(ChatMessageSchema.parse({ id: 'preference',session_id: 's',role: 'user',content }));
    f.knowledge.relationship.immediate('s','preference',content); assert.match(f.knowledge.context(f.state),/以后回答简短一点/);
    f.knowledge.savePreference({ kind: 'tone',content: '请详细解释' },'manual-correction');
    const restarted = new KnowledgeService(f.store,() => f.settings), other = { ...f.state,session_id: 'other' };
    assert.match(restarted.context(other),/请详细解释/); assert.doesNotMatch(restarted.context(other),/以后回答简短一点/);
    restarted.savePreference({ kind: 'tone',content: '' },'manual-delete'); assert.doesNotMatch(restarted.context(other),/请详细解释/);
    restarted.recordFocus('focus-one',25); restarted.recordFocus('focus-one',25);
    const experiences = restarted.repo.list('episodic_memory').filter(item => item.source === 'app_event');
    assert.equal(experiences.length,1); assert.match(experiences[0]!.content,/一起完成/);
    restarted.deleteMemory(experiences[0]!.id); restarted.recordFocus('focus-one',25);
    assert.equal(restarted.repo.get(experiences[0]!.id),undefined); assert.doesNotMatch(restarted.context(other),/一起完成/);
  } finally { await f.close(); }
});
test('context ranks hot memories by priority, excludes expired records and keeps irrelevant skill bodies out', async () => {
  const f = await fixture();
  try {
    for (const [id, priority, expires_at] of [['Low priority info', 10, null], ['High priority info', 99, null], ['Expired info', 100, '2000-01-01T00:00:00']] as const)
      f.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id, memory_type: 'user_profile', content: id, priority, expires_at }));
    f.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id: 'system', memory_type: 'system_profile', content: 'Be helpful' }));
    const context = f.knowledge.context(f.state);
    assert.ok(context.indexOf('High priority info') < context.indexOf('Low priority info')); assert.match(context, /Be helpful/); assert.doesNotMatch(context, /Expired info/);
    f.settings.memory_hot_user_profile_tokens = 5;
    assert.match(f.knowledge.context(f.state), /High priority info/);
    assert.doesNotMatch(f.knowledge.context(f.state), /Low priority info/);
    const before = f.knowledge.repo.list();
    for (const prompt of ['我是谁', '你是谁', 'who am I?', 'who are you?']) f.knowledge.prepare({ ...f.state, input_text: prompt });
    assert.deepEqual(f.knowledge.repo.list(), before);
    f.knowledge.prepare({ ...f.state, input_text: '以后叫你小满' });
    assert.equal(f.knowledge.repo.list('system_profile').find(item => item.source === 'strong_signal')!.source_message_id, 't');
  } finally { await f.close(); }
});
