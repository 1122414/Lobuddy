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
