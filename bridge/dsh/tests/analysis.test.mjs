import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AnalysisCalls } from '../dist/analysis.js';

test('auxiliary analysis has one bounded call, no tools or historical session', async () => {
  process.env.LOBUDDY_DSH_PROVIDER = 'fixture'; process.env.LOBUDDY_DSH_MODEL = 'fixture';
  let count = 0;
  const api = new AnalysisCalls({ llm: { stream: async function* (options) {
    count++;
    assert.equal(options.maxTokens, 1024); assert.deepEqual(options.tools, []);
    assert.equal(options.messages.length, 1); assert.equal(options.sessionId, undefined);
    yield { type: 'text-delta', text: '{}' }; yield { type: 'finish', reason: { kind: 'stop' } };
  } } });
  assert.deepEqual(await api.run({ id: 'a', prompt: 'facts' }), { text: '{}' });
  await assert.rejects(api.run({ id: 'b', prompt: '字'.repeat(3000) }));
  assert.equal(count, 1);
});

test('truncation and absent terminal finish never count as completed analysis', async () => {
  for (const terminal of [false, true]) {
    const api = new AnalysisCalls({ llm: { stream: async function* () {
      yield { type: 'text-delta', text: '{}' };
      if (terminal) yield { type: 'finish', reason: { kind: 'max-tokens' } };
    } } });
    await assert.rejects(api.run({ id: 'a', prompt: 'facts' }), /incomplete/);
  }
});

test('front-end preemption aborts the model and blocks overlapping auxiliary calls', async () => {
  let entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const api = new AnalysisCalls({ llm: { stream: async function* (options) {
    entered();
    await new Promise(resolve => options.signal.addEventListener('abort', resolve, { once: true }));
    yield { type: 'finish', reason: { kind: 'aborted' } };
  } } });
  const running = api.run({ id: 'a', prompt: 'facts' });
  await ready;
  await assert.rejects(api.run({ id: 'b', prompt: 'facts' }), /unavailable/);
  api.cancel('a');
  await assert.rejects(running, /incomplete/);
});
