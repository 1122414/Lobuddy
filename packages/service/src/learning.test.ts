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
