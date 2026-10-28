import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MemoryItemSchema, CompanionPolicySchema } from '@lobuddy/contracts';
import { FocusTimer } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { MemoryRepository } from './storage/memory.js';
import { MemoryProjection } from './knowledge/projection.js';
import { Companionship, proactiveInstruction } from './companion/policy.js';
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-companion-ts-'));
  const store = new Store(join(root, 'data/lobuddy.db'), { create: true }); await mkdir(join(root, 'workspace'));
  let now = 1_800_000_000;
  const companion = new Companionship(store, () => now), memory = new MemoryRepository(store);
  return { root, store, companion, memory, time: () => now, advance: (seconds: number) => { now += seconds; },
    close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}
function prepared(companion: Companionship): Companionship {
  // These cases test delivery policy independently of selection quality.
  companion.selectTopic = () => ({ topic_id: '', memory_id: '', revision: '', text: '一条已经准备好的话题。' });
  return companion;
}
test('focus pause, resume, completion and break have one owner and one completion callback', () => {
  let now = 0; const completed: string[] = [];
  const focus = new FocusTimer(() => ({ focus_default_minutes: 25, focus_break_minutes: 5, focus_auto_loop: true }), s => completed.push(s.id), () => now);
  focus.start(1); now = 30000; focus.pause(); assert.equal(focus.remaining, 30);
  now = 90000; focus.poll(); assert.equal(focus.remaining, 30); assert.equal(completed.length, 0);
  focus.resume(); now = 120000; focus.poll(); focus.poll(); assert.equal(completed.length, 1); assert.equal(focus.view().state, 'break');
  now += 300000; focus.poll(); assert.equal(focus.active, false); assert.equal(completed.length, 1);
  focus.start(); focus.stop(); now += 1800000; focus.poll(); assert.equal(completed.length, 1);
});
test('focus defaults, explicit duration, replacement and idle controls preserve the manager contract', () => {
  let now = 0; const completed: string[] = [];
  const focus = new FocusTimer(() => ({ focus_default_minutes: 25, focus_break_minutes: 5, focus_auto_loop: false }), s => completed.push(s.id), () => now);
  assert.equal(focus.active, false); assert.equal(focus.remaining, 0); assert.equal(focus.view().state, 'idle');
  focus.stop(); focus.pause(); focus.resume(); focus.poll(); assert.equal(focus.active, false);
  focus.start(); assert.equal(focus.remaining, 25 * 60); assert.equal(focus.session!.breakMinutes, 5);
  const original = focus.session!.id;
  now = 10000; focus.start(10);
  assert.notEqual(focus.session!.id, original); assert.equal(focus.remaining, 600); assert.equal(focus.active, true);
  const replacement = focus.session!.id;
  now += 600000; focus.poll(); focus.poll();
  assert.deepEqual(completed, [replacement]); assert.equal(focus.active, false); assert.equal(focus.remaining, 0);
  focus.start(30); assert.equal(focus.session!.minutes, 30);
  focus.stop(); focus.stop(); now += 3600000; focus.poll(); assert.deepEqual(completed, [replacement]);
});
test('proactive toggle accepts direct authorization but not quoted, hypothetical or question text', () => {
  for (const text of ['以后请不要主动找我聊天。','别打扰我','现在别再主动打扰我']) assert.equal(proactiveInstruction(text), false);
  for (const text of ['以后可以主动找我','允许你主动和我聊天！']) assert.equal(proactiveInstruction(text), true);
  for (const text of ['他说别打扰我','可以主动找我吗？','“别打扰我”','如果别打扰我']) assert.equal(proactiveInstruction(text), undefined);
});
test('proactive delay, focus, typing, running, quota and ignore cooldown persist across restarts', async () => {
  const f = await fixture();
  try {
    const c = prepared(f.companion); c.trigger({ event: 'app_returned' }); assert.equal(c.poll(false, false), null);
    f.advance(31); assert.equal(c.poll(true, false), null); assert.equal(c.poll(false, true), null);
    c.engage({ client: 'quick', typing: true, conversation: false }); assert.equal(c.poll(false, false), null);
    f.advance(11); const first = c.poll(false, false)!; assert.ok(first); assert.equal(c.state.used, 1);
    const restarted = prepared(new Companionship(f.store, f.time)); assert.equal(restarted.poll(false, false), null);
    assert.ok(restarted.state.cooldown_until > f.time());
    restarted.trigger({ event: 'app_returned' }); assert.equal(restarted.state.pending, '');
    f.advance(7201); restarted.trigger({ event: 'app_returned' }); f.advance(31);
    const next = restarted.poll(false, false)!; assert.ok(next);
    restarted.feedback({ notice_id: next.notice_id, action: 'ignored' });
    assert.equal(restarted.state.cooldown_until, f.time() + 7200);
    restarted.configure(CompanionPolicySchema.parse({ daily_limit: 0 })); f.advance(8000);
    restarted.trigger({ event: 'app_returned' }); f.advance(31); assert.equal(restarted.poll(false, false), null);
  } finally { await f.close(); }
});
test('three daily invitations cannot be replenished by restart or a backward clock', async () => {
  const f = await fixture();
  try {
    prepared(f.companion);
    for (let index = 0; index < 3; index++) {
      f.companion.trigger({ event: 'app_returned' }); f.advance(31);
      const notice = f.companion.poll(false, false)!; assert.ok(notice);
      assert.equal(f.companion.poll(false, false)!.notice_id, notice.notice_id);
      assert.equal(f.companion.state.used, index + 1);
      f.companion.feedback({ notice_id: notice.notice_id, action: 'ignored' });
      f.companion.trigger({ event: 'app_returned' }); f.advance(3600);
      assert.equal(f.companion.poll(false, false), null); f.advance(3601);
    }
    const restored = prepared(new Companionship(f.store, f.time));
    restored.trigger({ event: 'app_returned' }); f.advance(31);
    assert.equal(restored.poll(false, false), null); assert.equal(restored.state.used, 3);
    f.advance(-86400); assert.equal(restored.poll(false, false), null); assert.equal(restored.state.used, 3);
  } finally { await f.close(); }
});
test('focus, execution, typing, conversation and do-not-disturb consume no proactive quota', async () => {
  for (const blocked of ['focus', 'running', 'typing', 'conversation', 'dnd']) {
    const f = await fixture();
    try {
      prepared(f.companion);
      f.companion.trigger({ event: 'app_returned' }); f.advance(31);
      if (blocked === 'dnd') f.companion.configure(CompanionPolicySchema.parse({ do_not_disturb: true }));
      f.companion.engage({ client: 'quick', typing: blocked === 'typing', conversation: blocked === 'conversation' });
      assert.equal(f.companion.poll(blocked === 'focus', blocked === 'running'), null, blocked);
      assert.equal(f.companion.state.used, 0);
    } finally { await f.close(); }
  }
});
test('unanswered invitations expire and restart applies ignore cooldown without replay', async () => {
  const f = await fixture();
  try {
    prepared(f.companion);
    f.companion.trigger({ event: 'conversation_finished' }); f.advance(31); assert.ok(f.companion.poll(false, false));
    const restored = prepared(new Companionship(f.store, f.time)); assert.equal(restored.poll(false, false), null);
    assert.ok(restored.state.cooldown_until > f.time() + 7000);
    f.advance(7201); restored.trigger({ event: 'conversation_finished' }); f.advance(31); assert.ok(restored.poll(false, false));
    f.advance(21); assert.equal(restored.poll(false, false), null); assert.equal(restored.state.cooldown_until, f.time() + 7200);
  } finally { await f.close(); }
});
test('topic quotes canonical records, respects seven-day repetition, edits, permanent blocks and deleted sources', async () => {
  const f = await fixture();
  try {
    f.memory.save(MemoryItemSchema.parse({ id: 'm', memory_type: 'user_profile', title: '相处 · 饮料', content: '我喜欢红茶' }));
    const topics = f.companion.topics, selected = topics.choose()!; assert.match(selected.text, /我喜欢红茶/);
    topics.shown(selected); assert.equal(topics.choose(), undefined); assert.equal(topics.valid('m'), true);
    f.memory.save({ ...f.memory.get('m')!, content: '我现在喜欢白茶' });
    assert.equal(topics.valid('m'), false); assert.match(topics.choose()!.text, /白茶/);
    topics.shown(topics.choose()!); topics.feedback(selected.topic_id, 'never'); f.advance(8 * 86400);
    assert.equal(topics.choose(), undefined); topics.feedback(selected.topic_id, 'unblock'); assert.ok(topics.choose());
    f.memory.delete('m'); assert.equal(topics.valid('m'), false); assert.equal(topics.list()[0]!.label, '来源记忆已删除');
  } finally { await f.close(); }
});
test('topic repetition expires after seven days and permanent subject boundaries survive revised evidence', async () => {
  const f = await fixture();
  try {
    const item = MemoryItemSchema.parse({ id: 'tea', memory_type: 'user_profile', title: '茶', content: '我喜欢白茶', source: 'relationship' });
    f.memory.save(item); const choice = f.companion.topics.choose()!; f.companion.topics.shown(choice);
    f.advance(6 * 86400); assert.equal(f.companion.topics.choose(), undefined);
    f.advance(86401); assert.ok(f.companion.topics.choose());
    f.companion.respond('以后别提白茶');
    f.memory.save({ ...item, content: '我喜欢白茶和红茶' });
    const restored = new Companionship(f.store, f.time);
    assert.equal(restored.topics.choose(), undefined); assert.equal(restored.topics.list()[0]!.blocked, true);
    restored.topics.feedback(choice.topic_id, 'unblock'); assert.ok(restored.topics.choose());
  } finally { await f.close(); }
});
test('quoted boundaries do not suppress topics and private or hypothetical content is never proposed', async () => {
  const f = await fixture();
  try {
    const item = MemoryItemSchema.parse({ id: 'tea', memory_type: 'user_profile', title: '茶', content: '我喜欢白茶', source: 'relationship' });
    f.memory.save(item);
    for (const text of ['他说以后别提白茶', '以后别提白茶好吗？', '如果以后别提白茶', '「以后别提白茶」']) {
      f.companion.respond(text); assert.ok(f.companion.topics.choose(), text);
    }
    for (const content of ['我喜欢我的住址上海市某路123号', '我喜欢 sk-abc12345678901234567890', '如果我喜欢红茶']) {
      f.memory.save({ ...item, content }); assert.equal(f.companion.topics.choose(), undefined, content);
    }
    f.memory.save(item); f.companion.trigger({ event: 'app_returned' }); f.advance(31);
    assert.equal(f.companion.poll(false, false)!.memory_id, item.id);
    f.memory.delete(item.id); assert.equal(f.companion.poll(false, false), null);
    assert.equal(f.companion.topics.list()[0]!.label, '来源记忆已删除');
    f.companion.respond('暂时不聊'); assert.equal(f.companion.state.cooldown_until, f.time() + 7200);
    const overview = f.companion.topics.overview();
    assert.deepEqual(overview.verified_skills, []); assert.deepEqual(overview.experiences, []); assert.ok(overview.available.includes('文字交流'));
  } finally { await f.close(); }
});
test('generated memory projections clear the last fact, preserve handwritten empty files and exclude scoped relations', async () => {
  const f = await fixture();
  try {
    const p = new MemoryProjection(join(f.root, 'data'), join(f.root, 'workspace'));
    const item = MemoryItemSchema.parse({ id: 'm', memory_type: 'user_profile', content: '我喜欢红茶' });
    p.refresh([item]); assert.match(await readFile(join(f.root, 'workspace/USER.md'), 'utf8'), /红茶/);
    p.refresh([]); assert.doesNotMatch(await readFile(join(f.root, 'workspace/USER.md'), 'utf8'), /红茶/);
    await writeFile(join(f.root, 'workspace/USER.md'), 'handwritten'); p.refresh([]);
    assert.equal(await readFile(join(f.root, 'workspace/USER.md'), 'utf8'), 'handwritten');
    p.refresh([{ ...item, source: 'relationship', scope: 'private-session' }]);
    assert.equal(await readFile(join(f.root, 'workspace/USER.md'), 'utf8'), 'handwritten');
    await rm(join(f.root, 'data/memory'), { recursive: true }); await mkdir(join(f.root, 'outside'));
    await symlink(join(f.root, 'outside'), join(f.root, 'data/memory'));
    assert.throws(() => p.refresh([item]), /符号链接/);
  } finally { await f.close(); }
});
