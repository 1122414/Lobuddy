import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setImmediate as tick } from 'node:timers/promises';
import { ChatSessionSchema, LearningPolicySchema, OutcomeSchema, TurnSendSchema } from '@lobuddy/contracts';
import { contextDefinition } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { TurnRepository } from './storage/turns.js';
import { OutcomeRepository } from './storage/outcomes.js';
import { WorkflowRepository } from './storage/workflows.js';
import { WorkflowEvolution } from './knowledge/evolution.js';
import { LearningService } from './knowledge/learning.js';

test('already-optimized RSI skips do not starve the next authorized learning call', async () => {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-rsi-learning-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  let now = 1800000000,modelCalls = 0;
  const learning = new LearningService(store,() => false,() => now);
  try {
    const evolution = new WorkflowEvolution(new WorkflowRepository(store));
    const candidate = evolution.propose(contextDefinition('compact'),'减少纯格式开销',['synthetic-prior-trace']);
    await evolution.evaluate(candidate.version_id,new AbortController().signal);
    new ChatRepository(store).saveSession(ChatSessionSchema.parse({ id: 'session' }));
    const turns = new TurnRepository(store),state = turns.submit('request',TurnSendSchema.parse({ session_id: 'session',text: '整理合成资料' })).state;
    state.status = 'completed'; turns.save(state);
    new OutcomeRepository(store).save(OutcomeSchema.parse({ turn_id: state.turn_id,scenario: 'organize',verdict: 'verified',evidence: [{ checked: true }] }));
    await learning.configure(LearningPolicySchema.parse({ idle_seconds: 1,daily_calls: 1,daily_input_tokens: 8192,daily_output_tokens: 2048 }));
    const analyze = (prompt: string,signal: AbortSignal,max: 1024 | 2048) => learning.analyze(prompt,signal,async () => { modelCalls++; return '{}'; },max);
    learning.handlers.set('workflow_proposal',{ calls: 1,input_tokens: 8192,output_tokens: 2048,run: async (source,signal) => {
      const result = await evolution.generate(source,(prompt,max) => analyze(prompt,signal,max),signal,() => !signal.aborted);
      return result ? { version_id: result.version_id } : { skipped: 'no_verified_improvement_source' };
    } });
    learning.handlers.set('useful_analysis',{ calls: 1,input_tokens: 8192,output_tokens: 2048,run: async (_source,signal) => {
      await analyze('检查新任务的合成证据',signal,1024); return { checked: true };
    } });
    learning.enqueue('workflow_proposal',state.turn_id); learning.enqueue('useful_analysis','next');
    now += 2; learning.tick(); await tick();
    assert.equal(modelCalls,0); assert.equal(learning.repo.usage(now).calls,0);
    assert.deepEqual(learning.repo.jobs().find(job => job.kind === 'workflow_proposal')!.result,{ skipped: 'no_verified_improvement_source' });
    now += 2; learning.tick(); await tick();
    assert.equal(modelCalls,1); assert.equal(learning.repo.usage(now).calls,1);
    assert.equal(learning.repo.jobs().find(job => job.kind === 'useful_analysis')!.status,'completed');
    assert.equal(learning.view().state,'budget_exhausted');
  } finally { await learning.close(); store.close(); await rm(root,{ recursive: true,force: true }); }
});
