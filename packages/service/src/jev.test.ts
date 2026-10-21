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
  let now = 1800000000, quiet = false, key = 'synthetic-secret-token',calls = 0;
  let provider: JevClient = async () => response(); const bodies: Buffer[] = [];
  const notices = new NotificationRepository(store,() => now);
  const decisions = new NotificationDecisions(store,() => settings,notices,() => quiet,() => '处理任务',() => ({ key,secrets: [key] }),
    async (...args) => { calls++; bodies.push(args[0]); return provider(...args); },() => now);
  notices.eligible = notice => decisions.allowed(notice);
  const put = (id: string,text = '五分钟内需要处理任务',delegation = '') => {
    const notice = NotificationViewSchema.parse({ id,reason: 'task_result',source_id: id,delegation_id: delegation,text,planned_at: now,created_at: now });
    notices.put(notice); return notice;
  };
  return { root,store,settings,notices,decisions,put,bodies,calls: () => calls,clock: () => now,advance: (seconds: number) => { now += seconds; },
    quiet: (value: boolean) => { quiet = value; },key: (value: string) => { key = value; },provider: (value: JevClient) => { provider = value; },
    close: async () => { await decisions.stop(true); store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('Jev wire contract rejects invalid probabilities, confidence, invented options, fields and oversized context', () => {
  const value = response();
  assert.throws(() => JevResponseSchema.parse({ ...value,extra: true }));
  for (const change of [{ confidence: 0.1 },{ probabilities: { yes: 0.5,no: 0.5 } },{ choice: 'unknown' },{ probabilities: { yes: 1,no: 1,unknown: 0 } }]) {
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
    const notice = f.put('one'); f.key(''); assert.equal(f.decisions.allowed(notice),true); f.decisions.poll(); await tick(); assert.equal(f.calls(),0);
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
    ] as const) {
      f.put(id); f.provider(async () => result); f.decisions.poll(); await tick();
      const decision = f.decisions.repo.get(id)!; assert.equal(decision.action,action); assert.equal(decision.status,'decided');
      assert.equal(decision.input_tokens,120); assert.equal(decision.output_tokens,15);
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
    for (const [index,text] of ['我的住址是某路123号','sk-abcdefghijklmnopqrstuvwxyz123456','synthetic-secret-token'].entries()) {
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
