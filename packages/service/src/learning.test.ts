import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setImmediate as tick } from 'node:timers/promises';
import { LearningPolicySchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { LearningService } from './knowledge/learning.js';
import { LearningRepository } from './storage/learning.js';
test('learning reserves before calls, prioritizes activity, caps retries, and preserves reservations on restart', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-learning-ts-')), store = new Store(join(root, 'lobuddy.db'), { create: true });
  let now = 1800000000, calls = 0, busy = false;
  const service = new LearningService(store, () => busy, () => now);
  try {
    await service.configure(LearningPolicySchema.parse({ idle_seconds: 1, daily_calls: 2, daily_input_tokens: 200, daily_output_tokens: 20 }));
    service.handlers.set('memory', { calls: 1, input_tokens: 100, output_tokens: 10,
      run: async (_source, signal) => {
        calls++; assert.equal(service.repo.usage(now).calls, calls);
        await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }));
        signal.throwIfAborted(); return {};
      } });
    service.enqueue('memory', 'one'); service.enqueue('memory', 'one'); service.tick(); assert.equal(calls, 0);
    now += 2; busy = true; service.tick(); assert.equal(calls, 0); busy = false; now += 2;
    service.tick(); service.tick(); await tick(); assert.equal(calls, 1);
    await service.activity(); assert.equal(service.repo.jobs()[0]!.status, 'interrupted');
    now += 2; service.tick(); assert.equal(calls, 1);
    now += 301; service.tick(); await tick(); assert.equal(calls, 2); await service.activity();
    now += 301; service.tick(); assert.equal(calls, 2); assert.equal(service.view().state, 'budget_exhausted');
    await service.close();
    const restarted = new LearningService(store, () => false, () => now);
    try {
      assert.equal(restarted.repo.usage(now).calls, 2); assert.equal(restarted.repo.jobs()[0]!.attempts, 2);
      restarted.enqueue('memory', 'one'); assert.equal(restarted.repo.jobs().filter(job => job.kind === 'memory').length, 1);
      await restarted.configure(LearningPolicySchema.parse({ enabled: false }));
      restarted.enqueue('memory', 'two'); now += 1000; restarted.tick();
      assert.equal(restarted.repo.jobs().filter(job => job.kind === 'memory').length, 1);
    } finally { await restarted.close(); }
  } finally { await service.close(); store.close(); await rm(root, { recursive: true, force: true }); }
});
test('completed jobs persist their result and cannot run again after a new service owns the store', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-learning-completed-')), store = new Store(join(root, 'lobuddy.db'), { create: true });
  let now = 1800000000, calls = 0;
  const handler = { calls: 0, input_tokens: 0, output_tokens: 0, run: async () => { calls++; return { checked: true }; } };
  const service = new LearningService(store, () => false, () => now);
  try {
    service.handlers.set('test', handler); service.enqueue('test', 'one'); now += 61; service.tick(); await tick();
    assert.equal(calls, 1); await service.close(); assert.equal(service.view().state, 'closed');
    const restored = new LearningService(store, () => false, () => now);
    try {
      restored.handlers.set('test', handler); restored.enqueue('test', 'one'); now += 400; restored.tick(); await tick();
      assert.equal(calls, 1); assert.equal(restored.repo.jobs().length, 1);
      assert.deepEqual(restored.repo.jobs()[0]!.result, { checked: true });
    } finally { await restored.close(); }
  } finally { await service.close(); store.close(); await rm(root, { recursive: true, force: true }); }
});
test('each independent learning budget remains consumed across recovery and resets only on a new day', async () => {
  for (const limit of ['daily_calls', 'daily_input_tokens', 'daily_output_tokens']) {
    const root = await mkdtemp(join(tmpdir(), 'lobuddy-learning-limit-')), store = new Store(join(root, 'lobuddy.db'), { create: true });
    try {
      const now = 1800000000, repo = new LearningRepository(store), policy = LearningPolicySchema.parse({ [limit]: 1 });
      const amount = { calls: 1, input_tokens: 1, output_tokens: 1 };
      repo.enqueue('test', 'one', now); repo.enqueue('test', 'two', now);
      assert.ok(repo.claim('test', now, policy, amount));
      const restored = new LearningRepository(store); restored.recover(now);
      assert.equal(restored.claim('test', now + 400, policy, amount), undefined);
      assert.deepEqual(restored.usage(now), { day: restored.day(now), ...amount });
      assert.ok(restored.claim('test', now + 86400, policy, amount));
    } finally { store.close(); await rm(root, { recursive: true, force: true }); }
  }
});
test('failed background handlers expose sanitized failure and never retry after three attempts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-learning-errors-')), store = new Store(join(root, 'lobuddy.db'), { create: true });
  let now = 1800000000, calls = 0; const service = new LearningService(store, () => false, () => now);
  try {
    service.handlers.set('summary', { calls: 1, input_tokens: 100, output_tokens: 10, run: async () => { calls++; throw Error('private-token-never-store'); } });
    service.enqueue('summary', 'one');
    for (let i = 0; i < 6; i++) { now += 301; service.tick(); await tick(); }
    assert.equal(calls, 3); assert.doesNotMatch(JSON.stringify(service.view()), /private-token/);
    assert.equal(service.repo.jobs()[0]!.status, 'failed'); assert.equal(service.repo.usage(now).calls, 3);
  } finally { await service.close(); store.close(); await rm(root, { recursive: true, force: true }); }
});
test('completed no-call learning releases only its reservation day and stays completed after restart', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-learning-unused-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  let now = new Date(2026,9,22,23,58,0).getTime() / 1000,release!: () => void;
  const beforeMidnight = now,service = new LearningService(store,() => false,() => now);
  try {
    service.handlers.set('workflow_proposal',{ calls: 1,input_tokens: 8192,output_tokens: 2048,
      run: async () => { await new Promise<void>(resolve => { release = resolve; }); return { skipped: 'already_optimized' }; } });
    service.enqueue('workflow_proposal','trace'); now += 61; service.tick(); await tick();
    assert.equal(service.repo.usage(beforeMidnight).calls,1);
    now += 120;
    service.repo.enqueue('other','next-day',now);
    assert.ok(service.repo.claim('other',now,service.policy,{ calls: 2,input_tokens: 3,output_tokens: 4 }));
    release(); await tick();
    assert.deepEqual(service.repo.usage(beforeMidnight),{ day: service.repo.day(beforeMidnight),calls: 0,input_tokens: 0,output_tokens: 0 });
    assert.deepEqual(service.repo.usage(now),{ day: service.repo.day(now),calls: 2,input_tokens: 3,output_tokens: 4 });
    assert.equal(service.repo.jobs().find(job => job.kind === 'workflow_proposal')!.status,'completed');
    await service.close();
    const restored = new LearningService(store,() => false,() => now);
    try {
      restored.enqueue('workflow_proposal','trace');
      assert.equal(restored.repo.claim('workflow_proposal',now + 400,restored.policy,{ calls: 1,input_tokens: 8192,output_tokens: 2048 }),undefined);
      assert.equal(restored.repo.usage(beforeMidnight).calls,0);
      assert.equal(restored.repo.usage(now).calls,2);
    } finally { await restored.close(); }
  } finally { release?.(); await service.close(); store.close(); await rm(root,{ recursive: true,force: true }); }
});
test('a skipped retry releases no quota from an earlier failed attempt', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-learning-retry-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  let now = 1800000000,attempts = 0; const service = new LearningService(store,() => false,() => now);
  try {
    service.handlers.set('workflow_proposal',{ calls: 1,input_tokens: 8192,output_tokens: 2048,
      run: async () => { if (++attempts === 1) throw Error('unknown prior result'); return { skipped: 'no_eligible_source' }; } });
    service.enqueue('workflow_proposal','trace'); now += 61; service.tick(); await tick();
    now += 301; service.tick(); await tick();
    assert.equal(attempts,2); assert.equal(service.repo.jobs()[0]!.status,'completed');
    assert.deepEqual(service.repo.usage(now),{ day: service.repo.day(now),calls: 1,input_tokens: 8192,output_tokens: 2048 });
  } finally { await service.close(); store.close(); await rm(root,{ recursive: true,force: true }); }
});
for (const mode of ['success','provider_failure','caught_provider_failure','caught_validation_failure']) {
  test(`analysis invocation retains its complete reservation: ${mode}`,async () => {
    const root = await mkdtemp(join(tmpdir(),'lobuddy-learning-invoked-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
    let now = 1800000000,modelCalls = 0; const service = new LearningService(store,() => false,() => now);
    try {
      service.handlers.set('workflow_proposal',{ calls: 1,input_tokens: 8192,output_tokens: 2048,
        run: async (_source,signal) => {
          try {
            await service.analyze(mode === 'caught_validation_failure' ? 'x'.repeat(8193) : 'inspect',signal,async () => {
              modelCalls++; if (mode !== 'success') throw Error('unknown provider result'); return '{}';
            });
          } catch (error) { if (!mode.startsWith('caught_')) throw error; }
          return { skipped: 'no_improvement' };
        } });
      service.enqueue('workflow_proposal','trace'); now += 61; service.tick(); await tick();
      assert.equal(modelCalls,mode === 'caught_validation_failure' ? 0 : 1);
      assert.equal(service.repo.jobs()[0]!.status,mode === 'provider_failure' ? 'failed' : 'completed');
      assert.deepEqual(service.repo.usage(now),{ day: service.repo.day(now),calls: 1,input_tokens: 8192,output_tokens: 2048 });
    } finally { await service.close(); store.close(); await rm(root,{ recursive: true,force: true }); }
  });
}
test('unused reservation settlement is exactly once and rejects completion from an earlier attempt', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-learning-settlement-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  try {
    const repo = new LearningRepository(store),policy = LearningPolicySchema.parse({}),amount = { calls: 1,input_tokens: 100,output_tokens: 20 };
    const now = 1800000000;
    repo.enqueue('proposal','trace',now);
    const first = repo.claim('proposal',now,policy,amount)!;
    repo.finish(first,'failed',now);
    const retry = repo.claim('proposal',now + 301,policy,amount)!;
    repo.finish(first,'completed',now + 302,'{}','',true);
    assert.equal(repo.jobs()[0]!.status,'running'); assert.equal(repo.jobs()[0]!.attempts,2);
    assert.equal(repo.usage(now).calls,2);
    repo.finish(retry,'completed',now + 303,'{}','',true);
    repo.finish(retry,'completed',now + 304,'{}','',true);
    assert.equal(repo.jobs()[0]!.status,'completed');
    assert.deepEqual(repo.usage(now),{ day: repo.day(now),...amount });
  } finally { store.close(); await rm(root,{ recursive: true,force: true }); }
});
test('unused quota release and job completion roll back together when storage fails', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-learning-atomic-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  try {
    const repo = new LearningRepository(store),policy = LearningPolicySchema.parse({}),amount = { calls: 1,input_tokens: 100,output_tokens: 20 };
    const now = 1800000000; repo.enqueue('proposal','trace',now);
    const claim = repo.claim('proposal',now,policy,amount)!;
    store.connection.exec("CREATE TEMP TRIGGER deny_refund BEFORE UPDATE ON learning_budget WHEN NEW.calls<OLD.calls BEGIN SELECT RAISE(ABORT,'injected refund failure'); END");
    assert.throws(() => repo.finish(claim,'completed',now + 1,'{}','',true),/injected refund failure/);
    assert.equal(repo.jobs()[0]!.status,'running'); assert.deepEqual(repo.usage(now),{ day: repo.day(now),...amount });
    store.connection.exec('DROP TRIGGER deny_refund');
    repo.finish(claim,'completed',now + 2,'{}','',true);
    assert.equal(repo.jobs()[0]!.status,'completed'); assert.equal(repo.usage(now).calls,0);
  } finally { store.close(); await rm(root,{ recursive: true,force: true }); }
});
