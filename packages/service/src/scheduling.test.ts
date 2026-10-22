import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DelegationSpecSchema, DelegationConfirmSchema, RepeatRuleSchema } from '@lobuddy/contracts';
import { nextOccurrence, resolveWallTime, delegationJson } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { DelegationRepository } from './storage/delegations.js';
import { NotificationRepository } from './storage/notifications.js';
import { ScheduleRepository } from './storage/schedules.js';
const stamp = (value: string) => Date.parse(value) / 1000;
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-schedule-ts-')), store = new Store(join(root,'lobuddy.db'),{ create: true });
  let now = stamp('2026-10-21T09:00:00+08:00');
  const clock = () => now, delegations = new DelegationRepository(store,clock), notifications = new NotificationRepository(store,clock);
  const schedules = new ScheduleRepository(delegations,notifications,clock);
  notifications.valid = notice => !notice.delegation_id || !['paused','cancelled','draft','failed','needs_review'].includes(delegations.get(notice.delegation_id).status);
  const create = (id: string, changes: Record<string,unknown> = {}) => {
    const draft = delegations.create(id,DelegationSpecSchema.parse({ goal: '按约定提醒',kind: 'reminder',criteria: ['通知按规则投递（不代表已读）'],wait: { kind: 'time',at: now + 60 },...changes }));
    return delegations.change(`confirm-${id}`,'confirm',{ delegation_id: draft.id,revision: draft.revision,expires_at: now + 86400 * 30 });
  };
  return { store,root,clock,delegations,notifications,schedules,create,advance: (seconds: number) => { now += seconds; },
    close: async () => { schedules.release(); store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('calendar keeps the saved zone, rejects gaps, skips impossible recurrence and uses only the first fold', () => {
  assert.equal(resolveWallTime('2030-10-19T09:00','America/New_York'),stamp('2030-10-19T13:00:00Z'));
  assert.equal(resolveWallTime('2030-10-19T09:00','Asia/Shanghai'),stamp('2030-10-19T01:00:00Z'));
  for (const [wall,zone] of [['2026-03-08T02:30','America/New_York'],['2026-02-30T09:00','Asia/Shanghai'],['2030-10-19T09:00','not-a-zone'],['2030-10-19T09:00Z','Asia/Shanghai']]) assert.throws(() => resolveWallTime(wall!,zone!));
  assert.equal(resolveWallTime('2026-11-01T01:30','America/New_York'),stamp('2026-11-01T01:30:00-04:00'));
  for (const [frequency,after,expected] of [
    ['daily','2026-03-08T00:00:00-05:00','2026-03-09T02:30:00-04:00'],
    ['daily','2026-03-07T02:30:00-05:00','2026-03-09T02:30:00-04:00'],
    ['weekly','2026-03-07T00:00:00-05:00','2026-03-15T02:30:00-04:00'],
  ]) assert.equal(nextOccurrence(RepeatRuleSchema.parse({ frequency,local_time: '02:30',weekdays: frequency === 'weekly' ? [6] : [] }),'America/New_York',stamp(after!)),stamp(expected!));
  const rule = RepeatRuleSchema.parse({ frequency: 'daily',local_time: '01:30' });
  const first = nextOccurrence(rule,'America/New_York',stamp('2026-11-01T00:00:00-04:00'))!;
  assert.equal(first,stamp('2026-11-01T01:30:00-04:00'));
  assert.equal(nextOccurrence(rule,'America/New_York',first),stamp('2026-11-02T01:30:00-05:00'));
  const weekly = RepeatRuleSchema.parse({ frequency: 'weekly',local_time: '20:00',weekdays: [4],end_at: stamp('2026-10-23T21:00:00+08:00') });
  const end = nextOccurrence(weekly,'Asia/Shanghai',stamp('2026-10-19T12:00:00Z'))!;
  assert.equal(end,stamp('2026-10-23T20:00:00+08:00')); assert.equal(nextOccurrence(weekly,'Asia/Shanghai',end),null);
});
test('delegation request bytes preserve old Pydantic float defaults and scientific notation', async () => {
  const fixtures = JSON.parse(await readFile(new URL('../../../migration/fixtures/delegation-identity.json',import.meta.url),'utf8')) as { kind: string;input: unknown;serialized: string }[];
  for (const row of fixtures) {
    const value = row.kind === 'spec' ? DelegationSpecSchema.parse(row.input) : DelegationConfirmSchema.parse(row.input);
    assert.equal(delegationJson(value),row.serialized);
  }
});
test('delegation authority is explicit, revised edits invalidate it, and claimed versions cannot replay after crash', async () => {
  const f = await fixture();
  try {
    const spec = DelegationSpecSchema.parse({ goal: '归纳材料',kind: 'source-digest',sources: ['source.txt'],criteria: ['资料来源覆盖且引用可追溯'] });
    const draft = f.delegations.create('draft',spec); assert.deepEqual(f.delegations.create('draft',spec),draft);
    assert.throws(() => f.delegations.claim('early',{ delegation_id: draft.id,revision: 1 },'v1'),/尚未就绪/);
    const value = f.delegations.change('confirm','confirm',{ delegation_id: draft.id,revision: 1,expires_at: f.clock() + 100 });
    const params = { delegation_id: value.id,revision: value.revision };
    const claimed = f.delegations.claim('run',params,'v1'); assert.equal(claimed.created,true);
    assert.equal(f.delegations.claim('run',params,'v2').run.workflow_version,'v1');
    f.delegations.bind(claimed.run.id,'turn'); assert.throws(() => f.delegations.bind(claimed.run.id,'other'),/另一轮/);
    f.delegations.recover(); assert.equal(f.delegations.get(value.id).status,'needs_review');
    assert.equal(f.delegations.replayedRun('run',params)!.status,'interrupted'); assert.equal(f.delegations.claim('run',params,'v1').created,false);
    const reminder = f.create('editable');
    const edited = f.delegations.change('edit','edit',{ delegation_id: reminder.id,revision: reminder.revision,spec: { ...reminder.spec,goal: '换个目标' } });
    assert.equal(edited.status,'draft'); assert.equal(edited.authorized_at,null); assert.equal(edited.spec.wait.timezone,'Asia/Shanghai');
    assert.throws(() => f.delegations.change('stale','pause',{ delegation_id: reminder.id,revision: reminder.revision }),/已更新/);
    assert.equal(f.delegations.detail(reminder.id).revisions.length,3);
  } finally { await f.close(); }
});
test('execution completion is separate from verification; late success cannot revive paused or cancelled authority', async () => {
  const f = await fixture();
  try {
    for (const [index,[status,verdict,expected]] of ([['completed','verified','completed'],['completed','unknown','needs_review'],['failed','failed','failed'],['cancelled','unknown','needs_review']] as const).entries()) {
      const value = f.create(`outcome-${index}`,{ kind: 'source-digest',sources: ['source.txt'],criteria: ['资料来源覆盖且引用可追溯'],wait: { kind: 'none' } });
      const run = f.delegations.claim(`run-${index}`,{ delegation_id: value.id,revision: value.revision },'v1').run;
      f.delegations.bind(run.id,`turn-${index}`); f.delegations.settle(`turn-${index}`,status,verdict,'evidence');
      assert.equal(f.delegations.get(value.id).status,expected);
      const detail = f.delegations.detail(value.id); f.delegations.settle(`turn-${index}`,status,verdict,'duplicate'); assert.deepEqual(f.delegations.detail(value.id),detail);
    }
    assert.equal(f.store.connection.prepare("SELECT count(*) n FROM delegation_event WHERE kind='delegation_completed'").get()!.n,1);
    for (const action of ['pause','cancel']) {
      const value = f.create(action,{ kind: 'source-digest',sources: ['source.txt'],criteria: ['资料来源覆盖且引用可追溯'],wait: { kind: 'none' } });
      const run = f.delegations.claim(`run-${action}`,{ delegation_id: value.id,revision: value.revision },'v1').run;
      f.delegations.bind(run.id,action); f.delegations.change(`change-${action}`,action,{ delegation_id: value.id,revision: run.revision });
      f.delegations.settle(action,'completed','verified','late'); assert.equal(f.delegations.get(value.id).status,action === 'pause' ? 'paused' : 'cancelled');
    }
  } finally { await f.close(); }
});
test('scheduler commits a reminder once, leases one batch and completes only after displayed acknowledgement', async () => {
  const f = await fixture();
  try {
    const value = f.create('reminder'); f.advance(61); f.schedules.tick(); f.schedules.tick();
    assert.equal(f.notifications.list().length,1); assert.equal(f.delegations.get(value.id).status,'waiting_user');
    assert.equal(f.notifications.next(true),null); const batch = f.notifications.next(false)!; assert.ok(batch);
    assert.equal(f.notifications.next(false),null); assert.equal(f.notifications.displayed(batch.batch_id,true),false);
    f.advance(16); assert.equal(f.notifications.displayed(batch.batch_id,false),false);
    const replacement = f.notifications.next(false)!; assert.notEqual(replacement.batch_id,batch.batch_id);
    assert.equal(f.notifications.displayed(replacement.batch_id,false),true); f.schedules.completeDeliveries();
    assert.equal(f.delegations.get(value.id).status,'completed'); assert.equal(f.notifications.list()[0]!.read_at,null);
    f.notifications.read(f.notifications.list()[0]!.id); f.schedules.completeDeliveries();
    assert.equal(f.delegations.detail(value.id).runs.length,1);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM delegation_event').get()!.n,1);
    f.advance(-86400); f.schedules.tick(); assert.equal(f.notifications.next(false),null);
  } finally { await f.close(); }
});
test('missed periodic reminders coalesce, event chains survive restart and competing owners cannot duplicate delivery', async () => {
  const f = await fixture();
  try {
    const initial = f.create('daily',{ wait: { kind: 'time',at: f.clock() + 60 },repeat: { frequency: 'daily',local_time: '09:01' } });
    f.advance(86400 * 3); f.schedules.tick(); assert.equal(f.notifications.list().length,1);
    const other = new ScheduleRepository(f.delegations,f.notifications,f.clock); assert.deepEqual(other.tick(),[]);
    f.schedules.release(); other.tick(); assert.equal(f.notifications.list().length,1); other.release();
    const first = f.create('first'); const dependent = f.create('dependent',{ wait: { kind: 'event',event: 'delegation_completed',subject_id: first.id } });
    f.advance(61); f.schedules.tick(); const batch = f.notifications.next(false)!;
    f.notifications.displayed(batch.batch_id,false); f.schedules.completeDeliveries(); f.schedules.release();
    const restarted = new ScheduleRepository(new DelegationRepository(f.store,f.clock),f.notifications,f.clock);
    restarted.tick(); restarted.tick(); assert.equal(f.delegations.detail(dependent.id).runs.length,1); restarted.release();
    assert.ok(f.schedules.view(initial.id).next_at! > f.clock());
    const write = f.create('write',{ kind: 'organize-files',source_directory: 'in',output_directory: 'out',criteria: ['副本数量和内容校验通过，原文件保留'] });
    f.advance(61); f.schedules.tick(); assert.equal(f.delegations.get(write.id).status,'needs_review');
  } finally { await f.close(); }
});

test('missed reminder boundaries preserve inclusive one-day catchup and finish the last missed recurrence', async () => {
  for (const [late, expected] of [[30, 'pending'], [86400, 'pending'], [86401, 'missed']] as const) {
    const f = await fixture();
    try {
      const value = f.create('boundary'); f.advance(60 + late); f.schedules.tick();
      assert.equal(f.notifications.list()[0]!.status, expected); assert.equal(f.delegations.detail(value.id).runs.length, 1);
      f.schedules.tick(); assert.equal(f.notifications.list().length, 1);
    } finally { await f.close(); }
  }
  const f = await fixture();
  try {
    const value = f.create('last', { repeat: { frequency: 'daily', local_time: '09:01', catch_up: false, end_at: f.clock() + 100 } });
    f.advance(200); f.schedules.tick();
    assert.equal(f.notifications.list()[0]!.status, 'missed'); assert.equal(f.delegations.get(value.id).status, 'needs_review');
    assert.equal(f.schedules.view(value.id).next_at, null);
  } finally { await f.close(); }
});
test('paused, cancelled and expired authority cannot fire; event subject and owner leases deduplicate triggers', async () => {
  const f = await fixture();
  try {
    const value = f.create('pause'); f.schedules.tick();
    const paused = f.delegations.change('pause-action', 'pause', { delegation_id: value.id, revision: value.revision });
    f.advance(61); f.schedules.tick(); assert.deepEqual(f.notifications.list(), []);
    const resumed = f.delegations.change('resume', 'resume', { delegation_id: value.id, revision: paused.revision });
    f.delegations.change('cancel', 'cancel', { delegation_id: value.id, revision: resumed.revision });
    f.schedules.tick(); assert.deepEqual(f.notifications.list(), []);
    const expired = f.create('expiry'); f.advance(31 * 86400); f.schedules.tick();
    assert.equal(f.delegations.get(expired.id).status, 'needs_review'); assert.deepEqual(f.notifications.list(), []);
    const prerequisite = f.create('project-work', { wait: { kind: 'event', event: 'focus_finished' } });
    const event = f.create('event', { wait: { kind: 'event', event: 'delegation_completed', subject_id: prerequisite.id } });
    f.schedules.event('wrong', 'delegation_completed', 'unrelated'); f.schedules.tick(); assert.deepEqual(f.notifications.list(), []);
    const other = new ScheduleRepository(f.delegations, f.notifications, f.clock);
    f.schedules.event('right', 'delegation_completed', prerequisite.id); f.schedules.event('right', 'delegation_completed', prerequisite.id);
    assert.deepEqual(other.tick(), []); assert.deepEqual(f.notifications.list(), []);
    f.advance(11); other.tick(); f.schedules.tick(); other.tick();
    assert.equal(f.notifications.list().length, 1); assert.match(f.delegations.detail(event.id).runs[0]!.trigger_id, /right$/);
    other.release();
  } finally { await f.close(); }
});

test('expired unstarted manual delegations explain the authorization gap once without changing paused or active runs', async () => {
  const f = await fixture();
  try {
    const spec = { kind: 'source-digest', sources: ['note.txt'], criteria: ['资料来源覆盖且引用可追溯'] };
    const ready = f.create('manual', { ...spec, wait: { kind: 'none' } });
    const waiting = f.create('manual-user', { ...spec, wait: { kind: 'user' } });
    const pause = f.create('paused', { ...spec, wait: { kind: 'none' } });
    const paused = f.delegations.change('pause-manual', 'pause', { delegation_id: pause.id, revision: pause.revision });
    const active = f.create('active', { ...spec, wait: { kind: 'none' } });
    const run = f.delegations.claim('active-run', { delegation_id: active.id, revision: active.revision }, 'v1').run;
    f.advance(31 * 86400); f.schedules.tick();
    for (const value of [ready, waiting]) {
      const expired = f.delegations.get(value.id);
      assert.equal(expired.status, 'needs_review'); assert.match(expired.reason, /授权已到期/);
      assert.equal(expired.expires_at, value.expires_at); assert.equal(expired.authorized_at, value.authorized_at);
      f.schedules.tick(); assert.deepEqual(f.delegations.get(value.id), expired);
      assert.equal(f.delegations.detail(value.id).runs.length, 0);
    }
    assert.deepEqual(f.delegations.get(paused.id), paused);
    assert.equal(f.delegations.get(active.id).active_run_id, run.id);
    assert.equal(f.delegations.get(active.id).status, 'running'); assert.equal(f.delegations.active(run.id), false);
    assert.deepEqual(f.notifications.list(), []);
  } finally { await f.close(); }
});

test('unreachable completion dependencies become actionable while paused parents remain pending', async () => {
  for (const mode of ['cancelled', 'failed', 'missing', 'paused'] as const) {
    const f = await fixture();
    try {
      const parent = f.create('parent');
      const child = f.create('child', { wait: { kind: 'event', event: 'delegation_completed', subject_id: mode === 'missing' ? 'absent' : parent.id } });
      if (mode === 'cancelled' || mode === 'paused') f.delegations.change('parent-state', mode === 'paused' ? 'pause' : 'cancel', { delegation_id: parent.id, revision: parent.revision });
      if (mode === 'failed') { parent.status = 'failed'; parent.revision++; f.delegations.write(parent); }
      f.schedules.tick();
      const result = f.delegations.get(child.id);
      assert.equal(result.status, mode === 'paused' ? 'waiting_event' : 'needs_review');
      if (mode !== 'paused') assert.match(result.reason, /前置委托.*重新安排/);
      f.schedules.tick(); assert.deepEqual(f.delegations.get(child.id), result);
      assert.equal(f.delegations.detail(child.id).runs.length, 0); assert.deepEqual(f.notifications.list(), []);
    } finally { await f.close(); }
  }
});

test('an already verified completion event wins over later parent cancellation and dispatches only once', async () => {
  const f = await fixture();
  try {
    const parent = f.create('parent', { repeat: { frequency: 'daily', local_time: '09:01' } });
    const child = f.create('child', { wait: { kind: 'event', event: 'delegation_completed', subject_id: parent.id } });
    f.schedules.event('verified-first-run', 'delegation_completed', parent.id);
    f.delegations.change('cancel-after-completion', 'cancel', { delegation_id: parent.id, revision: parent.revision });
    f.schedules.tick(); f.schedules.tick();
    assert.equal(f.delegations.get(child.id).status, 'waiting_user');
    assert.equal(f.delegations.detail(child.id).runs.length, 1); assert.equal(f.notifications.list().length, 1);
  } finally { await f.close(); }
});
test('settlement crash resumes periodic read-only tasks only after verified evidence', async () => {
  for (const verdict of ['verified', 'unknown'] as const) {
    const f = await fixture();
    try {
      const value = f.create('daily', { kind: 'source-digest', sources: ['note.txt'], criteria: ['资料来源覆盖且引用可追溯'], repeat: { frequency: 'daily', local_time: '09:01' } });
      f.advance(60); const dispatch = f.schedules.tick()[0]!;
      const run = f.delegations.claim(dispatch.trigger, { delegation_id: value.id, revision: dispatch.revision }, 'fixed-version').run;
      f.delegations.bind(run.id, 'finished'); f.schedules.dispatched(dispatch.trigger);
      f.delegations.settle('finished', 'completed', verdict, 'evidence'); f.schedules.release();
      const restart = new ScheduleRepository(f.delegations, f.notifications, f.clock);
      assert.deepEqual(restart.tick(), []);
      assert.equal(f.delegations.get(value.id).status, verdict === 'verified' ? 'scheduled' : 'needs_review');
      f.advance(86400); const pending = restart.tick(); assert.equal(pending.length, verdict === 'verified' ? 1 : 0);
      if (pending.length) assert.notEqual(pending[0]!.trigger, dispatch.trigger);
      assert.equal(f.delegations.detail(value.id).runs.length, 1); restart.release();
    } finally { await f.close(); }
  }
});
test('notification batching keeps receipts separate, rejects revoked leases and survives a backwards clock', async () => {
  const f = await fixture();
  try {
    const { NotificationViewSchema } = await import('@lobuddy/contracts');
    for (let i = 0; i < 3; i++) f.notifications.put(NotificationViewSchema.parse({ id: String(i), reason: 'task_result', source_id: String(i), text: '结果', planned_at: f.clock(), created_at: f.clock() }));
    assert.equal(f.notifications.next(true), null);
    const batch = f.notifications.next(false)!; assert.equal(batch.count, 3); assert.equal(f.notifications.next(false), null);
    f.notifications.valid = () => false; assert.equal(f.notifications.displayed(batch.batch_id, false), false);
    f.notifications.valid = () => true;
    assert.equal(f.notifications.displayed(batch.batch_id, false), true); assert.equal(f.notifications.displayed(batch.batch_id, false), true);
    assert.ok(f.notifications.list().every(n => n.read_at === null && n.delivered_at === f.clock()));
    const receipt = f.notifications.read('0'); assert.equal(receipt.read_at, f.clock());
    f.advance(-100); f.schedules.tick(); f.advance(100); f.schedules.tick();
    assert.equal(f.notifications.next(false), null); assert.equal(f.notifications.list().length, 3);
    assert.equal(f.notifications.read('0').read_at, receipt.read_at);
  } finally { await f.close(); }
});

test('delegation replay validates request identity, source ownership, expiry and resumed scope', async () => {
  const f = await fixture();
  try {
    const spec = DelegationSpecSchema.parse({ goal: 'Review', kind: 'source-digest', sources: ['note.txt'], criteria: ['资料来源覆盖且引用可追溯'] });
    const value = f.delegations.create('create-draft', spec), restarted = new DelegationRepository(f.store, f.clock);
    assert.deepEqual(restarted.create('create-draft', spec), value); assert.equal(restarted.list().length, 1);
    assert.throws(() => restarted.create('create-draft', { ...spec, goal: 'Different' }), /请求 ID/);
    for (const fields of [{ session_id: 'missing' }, { source_message_id: 'missing' }]) assert.throws(() => restarted.create('bad-source', DelegationSpecSchema.parse({ ...spec, ...fields })), /来源/);
    for (const expires_at of [f.clock() - 1, f.clock()]) assert.throws(() => restarted.change('expired-confirm', 'confirm', { delegation_id: value.id, revision: value.revision, expires_at }), /有效期/);
    const params = { delegation_id: value.id, revision: value.revision, expires_at: f.clock() + 100 };
    const ready = restarted.change('valid-confirm', 'confirm', params);
    assert.equal(ready.authorized_at, f.clock()); assert.equal(ready.revision, 2); assert.equal(ready.status, 'ready');
    assert.deepEqual(restarted.change('valid-confirm', 'confirm', params), ready);
    assert.throws(() => restarted.change('stale-cancel', 'cancel', { delegation_id: value.id, revision: 1 }), /已更新/);
    const pauseParams = { delegation_id: value.id, revision: ready.revision };
    const paused = restarted.change('pause-draft', 'pause', pauseParams);
    assert.deepEqual(restarted.change('pause-draft', 'pause', pauseParams), paused);
    assert.throws(() => restarted.claim('paused-run', { delegation_id: value.id, revision: paused.revision }, 'v1'), /就绪/);
    const resumed = restarted.change('resume-draft', 'resume', { delegation_id: value.id, revision: paused.revision });
    assert.equal(resumed.status, 'ready'); assert.deepEqual(resumed.spec, spec);
    f.advance(101); assert.throws(() => restarted.claim('expired-run', { delegation_id: value.id, revision: resumed.revision }, 'v1'), /到期/);
    assert.equal(restarted.detail(value.id).runs.length, 0);
  } finally { await f.close(); }
});
