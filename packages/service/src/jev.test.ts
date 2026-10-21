import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setImmediate as tick } from 'node:timers/promises';
import { NotificationViewSchema, JevResponseSchema, type ChoiceAnswer, type JevResponse } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { runtimeSettings } from './config/settings.js';
import { NotificationRepository } from './storage/notifications.js';
import { JevRepository } from './storage/jev.js';
import { NotificationDecisions } from './companion/decisions.js';
import { JevUnavailable, jevRequestBody, type JevClient } from './engine/jev.js';
const answer = (choice: ChoiceAnswer['choice'], confidence = 0.9): ChoiceAnswer => {
  const peak = confidence * (2 / 3) + 1 / 3;
  const probabilities = Object.fromEntries(['yes','no','unknown'].map(key => [key,key === choice ? peak : (1 - peak) / 2]));
  return { type: 'choice',choice,confidence,probabilities };
};
const response = (relevant = answer('yes'), urgent = answer('yes'), duplicate = answer('no')): JevResponse =>
  JevResponseSchema.parse({ model: 'jev-1.13.0',answers: { relevant,time_sensitive: urgent,duplicate },usage: { input_tokens: 120,output_tokens: 15 } });
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-jev-ts-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  const settings = runtimeSettings({ data: root,workspace: root,logs: root }); settings.jev_mode = 'active';
  let now = 1800000000, quiet = false, key = 'synthetic-secret-token',calls = 0, goal = '处理任务';
  let provider: JevClient = async () => response(); const bodies: Buffer[] = [];
  const notices = new NotificationRepository(store,() => now);
  const decisions = new NotificationDecisions(store,() => settings,notices,() => quiet,() => goal,() => ({ key,secrets: [key] }),
    async (...args) => { calls++; bodies.push(args[0]); return provider(...args); },() => now);
  notices.eligible = notice => decisions.allowed(notice);
  const put = (id: string,text = '五分钟内需要处理任务',delegation = '') => {
    const notice = NotificationViewSchema.parse({ id,reason: 'task_result',source_id: id,delegation_id: delegation,text,planned_at: now,created_at: now });
    notices.put(notice); return notice;
  };
  return { root,store,settings,notices,decisions,put,bodies,calls: () => calls,clock: () => now,advance: (seconds: number) => { now += seconds; },
    quiet: (value: boolean) => { quiet = value; },goal: (value: string) => { goal = value; },key: (value: string) => { key = value; },provider: (value: JevClient) => { provider = value; },
    close: async () => { await decisions.stop(true); store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('Jev wire contract rejects invalid probabilities, confidence, invented options, fields and oversized context', () => {
  const value = response();
  assert.throws(() => JevResponseSchema.parse({ ...value,extra: true }));
  for (const change of [{ confidence: 0.1 },{ confidence: NaN },{ choice: 'execute_shell' },
    { probabilities: { yes: 0.5,no: 0.5 } },{ choice: 'unknown' },{ probabilities: { yes: 1,no: 1,unknown: 0 } },
    { probabilities: { yes: 1.2,no: -0.1,unknown: -0.1 } }]) {
    assert.throws(() => JevResponseSchema.parse({ ...value,answers: { ...value.answers,relevant: { ...value.answers.relevant,...change } } }));
  }
  const body = jevRequestBody({ notification: '五分钟内提交',goal: '提交材料',recent_delivered: [] },'jev-1.13.0');
  const parsed = JSON.parse(body.toString()); assert.deepEqual(Object.keys(parsed.questions),['relevant','time_sensitive','duplicate']);
  assert.match(parsed.questions.time_sensitive.instructions,/ten minutes/); assert.match(parsed.questions.duplicate.instructions,/untrusted data/);
  assert.throws(() => jevRequestBody({ notification: '长'.repeat(601),goal: '',recent_delivered: [] },'jev-1.13.0'));
});
test('Jev preserves unconfigured and shadow behavior; quiet state skips calls and explicit reminders bypass decisions', async () => {
  const f = await fixture();
  try {
    const notice = f.put('one');
    for (const [mode,key] of [['off','synthetic-secret-token'],['active',''],['shadow','']] as const) {
      f.settings.jev_mode = mode; f.key(key); assert.equal(f.decisions.allowed(notice),true); f.decisions.poll(); await tick(); assert.equal(f.calls(),0);
    }
    f.settings.jev_mode = 'active';
    f.key('synthetic-secret-token'); f.quiet(true); f.decisions.poll(); await tick(); assert.equal(f.calls(),0);
    assert.equal(f.decisions.allowed({ ...notice,reason: 'reminder' }),true);
    f.quiet(false); f.settings.jev_mode = 'shadow'; assert.equal(f.decisions.allowed(notice),true);
    f.decisions.poll(); await tick(); assert.equal(f.calls(),1); assert.equal(f.decisions.repo.get(notice.id)!.mode,'shadow');
    f.settings.jev_mode = 'active'; assert.equal(f.decisions.allowed(notice),true,'Shadow observations never become retroactive delivery gates');
  } finally { await f.close(); }
});
test('Jev independent veto beats uncertain urgency, while confident urgent evidence permits notification', async () => {
  const f = await fixture();
  try {
    for (const [id,result,action] of [
      ['urgent',response(),'notify'],['irrelevant',response(answer('no'),answer('unknown',0.1)),'quiet'],
      ['duplicate',response(answer('unknown',0.1),answer('unknown',0.1),answer('yes')),'quiet'],
      ['uncertain',response(answer('yes'),answer('unknown',0.1)),'defer'],['ordinary',response(answer('yes'),answer('no')),'defer'],
      ['unknown-relevance',response(answer('unknown')),'defer'],['low-confidence',response(answer('yes',0.4)),'defer'],
    ] as const) {
      f.put(id); f.provider(async () => result); f.decisions.poll(); await tick();
      const decision = f.decisions.repo.get(id)!; assert.equal(decision.action,action); assert.equal(decision.status,'decided');
      assert.equal(decision.input_tokens,120); assert.equal(decision.output_tokens,15);
      const notice = f.notices.get(id)!;
      assert.equal(f.decisions.allowed(notice),action === 'notify');
      f.advance(601); assert.equal(f.decisions.allowed(notice),action !== 'quiet');
      f.notices.read(id);
    }
    assert.doesNotMatch(JSON.stringify(f.decisions.view()),/五分钟内需要处理任务|synthetic-secret-token/);
  } finally { await f.close(); }
});
test('Jev reservations survive restart, exhausted calls or bytes do not retry and failures retain the inbox', async () => {
  const f = await fixture();
  try {
    f.settings.jev_daily_calls = 1; f.provider(async () => { throw new JevUnavailable('http_402'); });
    const first = f.put('failed'); f.decisions.poll(); await tick();
    assert.equal(f.decisions.repo.get(first.id)!.status,'fallback'); assert.equal(f.decisions.allowed(first),false);
    f.decisions.poll(); await tick(); assert.equal(f.calls(),1);
    f.advance(601); assert.equal(f.decisions.allowed(first),true);
    f.put('over-budget'); f.decisions.poll(); await tick(); assert.equal(f.calls(),1);
    assert.equal(f.decisions.repo.get('over-budget')!.status,'fallback');
    const restarted = new JevRepository(f.store); assert.equal(restarted.usage(f.clock()).calls,1);
    f.settings.jev_daily_calls = 30; f.settings.jev_daily_request_bytes = 0;
    f.put('bytes'); f.decisions.poll(); await tick(); assert.equal(f.calls(),1);
    assert.equal(f.notices.list().length,3); assert.equal(f.decisions.repo.get('bytes')!.status,'fallback');
  } finally { await f.close(); }
});
test('Jev concurrent polls use one owner, cancelled or stale results never become active, and private text never leaves', async () => {
  const f = await fixture();
  try {
    let finish!: (result: JevResponse) => void;
    f.provider(() => new Promise(resolve => { finish = resolve; })); f.put('late');
    f.decisions.poll(); f.decisions.poll(); await tick(); assert.equal(f.calls(),1);
    f.quiet(true); finish(response()); await tick(); assert.equal(f.decisions.repo.get('late')!.status,'stale');
    f.quiet(false);
    for (const [index,text] of ['我的住址是某路123号','sk-abcdefghijklmnopqrstuvwxyz123456','synthetic-secret-token',
      '我的密码 abc123','我的工资信息','联系 test@example.com'].entries()) {
      f.put(`private-${index}`,text); f.decisions.poll(); await tick();
      assert.equal(f.calls(),1); assert.equal(f.decisions.repo.get(`private-${index}`)!.status,'fallback');
    }
    const current = f.put('cancelled');
    f.provider(async (_body,_key,signal) => {
      await new Promise<void>(resolve => signal.addEventListener('abort',() => resolve(),{ once: true })); signal.throwIfAborted(); return response();
    });
    f.decisions.poll(); await tick(); await f.decisions.stop();
    assert.equal(f.decisions.repo.get(current.id)!.status,'interrupted'); f.decisions.poll(); await tick(); assert.equal(f.calls(),2);
  } finally { await f.close(); }
});

test('Jev late decisions are invalidated by cancellation, goal edits, disable and read feedback', async () => {
  for (const change of ['cancel','goal','disable','read'] as const) {
    const f = await fixture();
    try {
      let finish!: (value: JevResponse) => void;
      f.provider(() => new Promise(resolve => { finish = resolve; }));
      const notice = f.put('late','五分钟内处理任务','same'); f.decisions.poll(); await tick();
      assert.equal(f.calls(),1);
      let stopping: Promise<void> | undefined;
      if (change === 'cancel') f.notices.cancelFor('same');
      if (change === 'goal') f.goal('已经改变的目标');
      if (change === 'read') f.notices.read(notice.id);
      if (change === 'disable') { f.settings.jev_mode = 'off'; stopping = f.decisions.stop(); }
      finish(response()); await stopping; await tick();
      const decision = f.decisions.repo.get(notice.id)!;
      assert.ok(['stale','interrupted'].includes(decision.status)); assert.equal(decision.action,'defer');
      // Turning Jev off restores the original inbox delivery policy.
      if (change === 'disable') assert.equal(f.notices.next(false)!.count,1);
      else assert.equal(f.notices.next(false),null);
    } finally { await f.close(); }
  }
});

test('Jev unknown reservations recover without retry or budget reset, including pending notices beyond the UI page', async () => {
  const f = await fixture();
  try {
    f.put('old-pending');
    for (let i = 0; i < 501; i++) { f.put(`read-${i}`); f.notices.read(`read-${i}`); }
    assert.equal(f.notices.list().length,500);
    f.decisions.poll(); await tick(); assert.equal(f.calls(),1); assert.equal(f.decisions.repo.get('old-pending')!.action,'notify');
    const record = f.decisions.repo.get('old-pending')!;
    f.decisions.repo.finish('old-pending',{ ...record,status: 'running',action: 'defer' });
    const recovered = new JevRepository(f.store);
    assert.equal(recovered.get('old-pending')!.status,'interrupted'); assert.equal(recovered.usage(f.clock()).calls,1);
    f.decisions.poll(); await tick(); assert.equal(f.calls(),1);
  } finally { await f.close(); }
});

test('Jev context includes only valid delivered history from the same delegation', async () => {
  const f = await fixture();
  try {
    const notice = f.put('current','五分钟内处理任务','same');
    for (const [id,delegation] of [['same-history','same'],['other-history','other']]) {
      const old = f.put(id!,id!,delegation!); f.notices.read(old.id);
    }
    const context = f.decisions.context(notice);
    assert.deepEqual(context.recent_delivered,['same-history']); assert.equal(context.goal,'处理任务');
    f.decisions.poll(); await tick();
    const wire = JSON.parse(f.bodies[0]!.toString()); assert.deepEqual(wire.state,context);
    const used = f.decisions.repo.usage(f.clock()); assert.equal(used.bytes,f.bodies[0]!.length);
    f.settings.jev_daily_request_bytes = used.bytes;
    f.put('blocked'); f.decisions.poll(); await tick(); assert.equal(f.calls(),1);
    assert.deepEqual(f.decisions.repo.usage(f.clock()),used);
  } finally { await f.close(); }
});
