import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatSessionSchema, TurnSendSchema, OutcomeSchema, PetStateSchema } from '@lobuddy/contracts';
import { addExperience, requiredExp, rewardCompletion } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { TurnRepository } from './storage/turns.js';
import { RuntimeLedger } from './storage/ledger.js';
import { PetRepository } from './storage/pet.js';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-ledger-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  new ChatRepository(store).saveSession(ChatSessionSchema.parse({ id: 'session', title: '新对话' }));
  const turns = new TurnRepository(store), ledger = new RuntimeLedger(store, turns);
  const send = (id: string) => turns.submit(id, TurnSendSchema.parse({ session_id: 'session', text: '你好' }));
  return { store, turns, ledger, send, clean: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}
test('durable request identity preserves the original turn and rejects different normalized content', async () => {
  const f = await fixture();
  try {
    const first = f.send('request'); assert.ok(first.created);
    assert.deepEqual(f.send('request'), { state: first.state, created: false });
    assert.throws(() => f.turns.submit('request', TurnSendSchema.parse({ session_id: 'session', text: '不同内容' })), /冲突/);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM chat_message').get()!.n, 1);
  } finally { await f.clean(); }
});
test('terminal state, reply, EXP, outcome and completion events settle once in one transaction', async () => {
  const f = await fixture();
  try {
    const state = f.send('request').state; state.status = 'completed'; state.output_text = '完成';
    f.ledger.recordSkillUse(state, 'skill'); f.ledger.recordSkillUse(state, 'skill');
    assert.throws(() => f.ledger.finish(state, () => { throw Error('injected commit failure'); }), /injected/);
    assert.equal(f.turns.get(state.turn_id).status, 'queued');
    for (const table of ['turn_settlement', 'task_record', 'task_result', 'service_event']) assert.equal(f.store.connection.prepare(`SELECT count(*) n FROM ${table}`).get()!.n, 0);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM chat_message').get()!.n, 1);
    const result = f.ledger.finish(state); assert.equal(result.progress.exp_gained, 5); assert.equal(result.events.length, 3);
    assert.deepEqual(f.ledger.finish(state), { progress: result.progress, events: [] });
    assert.equal(f.ledger.summary().pet.exp, 5); assert.equal(f.ledger.outcomes.get(state.turn_id).verdict, 'unknown');
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM skill_use').get()!.n, 1);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM chat_message').get()!.n, 2);
  } finally { await f.clean(); }
});
test('failure, cancellation and interruption never gain EXP or retain verified cancellation', async () => {
  const f = await fixture();
  try {
    const before = f.ledger.summary().pet;
    for (const status of ['failed', 'cancelled', 'interrupted'] as const) {
      const state = f.send(status).state; state.status = status;
      if (status !== 'failed') f.ledger.outcomes.save(OutcomeSchema.parse({ turn_id: state.turn_id, verdict: 'verified', scenario: 'files' }));
      assert.equal(f.ledger.finish(state).progress.exp_gained, 0);
      assert.equal(f.ledger.outcomes.get(state.turn_id).verdict, 'unknown');
      assert.deepEqual(f.ledger.summary().pet.personality, before.personality);
      assert.equal(f.store.connection.prepare('SELECT count(*) n FROM unlocked_abilities').get()!.n, 0);
    }
    assert.equal(f.ledger.summary().pet.exp, 0);
  } finally { await f.clean(); }
});
test('usage is deduplicated and disjoint cache counts are included exactly once', async () => {
  const f = await fixture();
  try {
    const state = f.send('usage').state, value = { inputTokens: 10, outputTokens: 4, cacheReadTokens: 5, cacheWriteTokens: 3 };
    f.ledger.usage(state, 4, value); f.ledger.usage(state, 4, value);
    assert.deepEqual(f.ledger.summary().usage, { input: 18, output: 4, cached: 8, calls: 1 });
    assert.throws(() => f.ledger.usage(state, 5, { inputTokens: Number.MAX_SAFE_INTEGER, outputTokens: 1, cacheReadTokens: 1 }), /溢出/);
  } finally { await f.clean(); }
});
test('recovery interrupts unfinished work and rotates blocked engine identity only on a new request', async () => {
  const f = await fixture();
  try {
    const state = f.send('old').state; state.status = 'running'; f.turns.save(state); f.turns.markEngineReady(state.engine_id);
    f.ledger.recover(); assert.equal(f.turns.get(state.turn_id).status, 'interrupted');
    f.ledger.recover(); assert.equal(f.ledger.summary().pet.exp, 0);
    assert.equal(f.send('old').state.engine_id, state.engine_id);
    const fresh = f.send('new'); assert.notEqual(fresh.state.engine_id, state.engine_id); assert.equal(f.turns.engineReady(fresh.state.engine_id), false);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM service_event').get()!.n, 3);
  } finally { await f.clean(); }
});
test('unknown writes are not replayed and independent acceptance failures dominate merged evidence', async () => {
  const f = await fixture();
  try {
    const state = f.send('effect').state;
    f.ledger.outcomes.claimEffect('write-1', state.turn_id, JSON.stringify({ output: 'synthetic' }));
    assert.throws(() => f.ledger.outcomes.claimEffect('write-2', state.turn_id, '{}'), /不能自动重放/);
    f.ledger.outcomes.save(OutcomeSchema.parse({ turn_id: state.turn_id, verdict: 'verified', scenario: 'organize', criteria: ['hash'] }));
    f.ledger.outcomes.save(OutcomeSchema.parse({ turn_id: state.turn_id, verdict: 'failed', scenario: 'digest', criteria: ['sources'] }));
    assert.equal(f.ledger.outcomes.get(state.turn_id).verdict, 'failed');
    assert.deepEqual(f.ledger.outcomes.get(state.turn_id).criteria, ['hash', 'sources']);
    const mixed = f.send('mixed').state;
    f.ledger.outcomes.save(OutcomeSchema.parse({ turn_id: mixed.turn_id, scenario: 'organize', reason: '仅预览，未复制' }));
    f.ledger.outcomes.save(OutcomeSchema.parse({ turn_id: mixed.turn_id, scenario: 'digest', verdict: 'verified', reason: '来源完整' }));
    assert.equal(f.ledger.outcomes.get(mixed.turn_id).verdict, 'unknown');
    assert.match(f.ledger.outcomes.get(mixed.turn_id).reason, /未复制/);
  } finally { await f.clean(); }
});
test('legacy EXP thresholds, stage transitions and capped traits retain their original behavior', () => {
  assert.deepEqual(Array.from({ length: 10 }, (_, i) => requiredExp(i + 1)), [50,120,220,350,520,720,950,1220,1550,9999]);
  const pet = PetStateSchema.parse({}); assert.equal(addExperience(pet, 50 + 120 + 220), true);
  assert.equal(pet.level, 4); assert.equal(pet.evolution_stage, 2); assert.equal(pet.exp, 0);
  assert.throws(() => addExperience(pet, -1));
  const reward = rewardCompletion(PetStateSchema.parse({ personality: { technical_skill: 99.9 } }), 'code api debug python');
  assert.equal(reward.pet.personality.technical_skill, 100); assert.equal(reward.pet.personality.interaction_counts['technical_skill:task_analysis'], 1);
  assert.equal(rewardCompletion(PetStateSchema.parse({}), '中文code中文').pet.personality.technical_skill, 50);
});
test('legacy small rewards, overflow rewards and every evolution boundary retain pet identity', () => {
  for (const [amount, level, exp, changed] of [[5, 1, 5, false], [60, 2, 10, true], [200, 3, 30, true]] as const) {
    const pet = PetStateSchema.parse({ id: 'original-pet', name: 'Test' });
    assert.equal(addExperience(pet, amount), changed);
    assert.equal(pet.level, level); assert.equal(pet.exp, exp); assert.equal(pet.id, 'original-pet');
  }
  for (const [level, stage] of [[1, 1], [3, 1], [4, 2], [7, 2], [8, 3]] as const) {
    const pet = PetStateSchema.parse({});
    addExperience(pet, Array.from({ length: level - 1 }, (_, i) => requiredExp(i + 1)).reduce((a, b) => a + b, 0));
    assert.equal(pet.level, level); assert.equal(pet.evolution_stage, stage);
  }
  const pet = PetStateSchema.parse({ exp: 10 });
  assert.throws(() => addExperience(pet, -5)); assert.equal(pet.exp, 10);
});
test('earned abilities survive a database reopen and repeated settlement never duplicates unlocks', async () => {
  const f = await fixture();
  try {
    new PetRepository(f.store).save(PetStateSchema.parse({ id: 'default', level: 2, exp: 115 }));
    const state = f.send('unlock').state; state.status = 'completed'; state.output_text = 'done';
    const first = f.ledger.finish(state);
    assert.deepEqual(first.progress.unlocked_abilities.map(([id]) => id), ['advanced_chat']);
    f.ledger.finish(state);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM unlocked_abilities').get()!.n, 1);
    const path = f.store.connection.prepare('PRAGMA database_list').get()!.file as string;
    f.store.close();
    const reopened = new Store(path);
    try {
      const ledger = new RuntimeLedger(reopened, new TurnRepository(reopened));
      const overview = ledger.summary();
      assert.equal(overview.pet.id, 'default'); assert.equal(overview.pet.level, 3);
      assert.ok(overview.abilities.find(value => value.id === 'advanced_chat')!.unlocked_at);
      ledger.finish(state);
      assert.equal(reopened.connection.prepare('SELECT count(*) n FROM unlocked_abilities').get()!.n, 1);
      const result = reopened.connection.prepare('SELECT success,raw_result,summary FROM task_result WHERE task_id=?').get(state.task_id)!;
      assert.deepEqual({ ...result }, { success: 1, raw_result: 'done', summary: 'done' });
    } finally { reopened.close(); }
  } finally { await f.clean(); }
});
