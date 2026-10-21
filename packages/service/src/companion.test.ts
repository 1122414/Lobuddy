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
test('focus pause, resume, completion and break have one owner and one completion callback', () => {
  let now = 0; const completed: string[] = [];
  const focus = new FocusTimer(() => ({ focus_default_minutes: 25, focus_break_minutes: 5, focus_auto_loop: true }), s => completed.push(s.id), () => now);
  focus.start(1); now = 30000; focus.pause(); assert.equal(focus.remaining, 30);
  now = 90000; focus.poll(); assert.equal(focus.remaining, 30); assert.equal(completed.length, 0);
  focus.resume(); now = 120000; focus.poll(); focus.poll(); assert.equal(completed.length, 1); assert.equal(focus.view().state, 'break');
  now += 300000; focus.poll(); assert.equal(focus.active, false); assert.equal(completed.length, 1);
  focus.start(); focus.stop(); now += 1800000; focus.poll(); assert.equal(completed.length, 1);
});
test('proactive toggle accepts direct authorization but not quoted, hypothetical or question text', () => {
  for (const text of ['以后请不要主动找我聊天。','别打扰我','现在别再主动打扰我']) assert.equal(proactiveInstruction(text), false);
  for (const text of ['以后可以主动找我','允许你主动和我聊天！']) assert.equal(proactiveInstruction(text), true);
  for (const text of ['他说别打扰我','可以主动找我吗？','“别打扰我”','如果别打扰我']) assert.equal(proactiveInstruction(text), undefined);
});
test('proactive delay, focus, typing, running, quota and ignore cooldown persist across restarts', async () => {
  const f = await fixture();
  try {
    const c = f.companion; c.trigger({ event: 'app_returned' }); assert.equal(c.poll(false, false), null);
    f.advance(31); assert.equal(c.poll(true, false), null); assert.equal(c.poll(false, true), null);
    c.engage({ client: 'quick', typing: true, conversation: false }); assert.equal(c.poll(false, false), null);
    f.advance(11); const first = c.poll(false, false)!; assert.ok(first); assert.equal(c.state.used, 1);
    const restarted = new Companionship(f.store, f.time); assert.equal(restarted.poll(false, false), null);
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
