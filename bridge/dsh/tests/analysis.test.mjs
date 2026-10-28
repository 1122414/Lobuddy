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
    await assert.rejects(api.run({ id: 'a', prompt: 'facts' }), /incomplete|truncated/);
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

test('larger method output remains explicitly bounded', async () => {
  const api = new AnalysisCalls({ llm: { stream: async function* (options) {
    assert.equal(options.maxTokens, 2048);
    yield { type: 'text-delta', text: '{}' }; yield { type: 'finish', reason: { kind: 'stop' } };
  } } });
  assert.deepEqual(await api.run({ id: 'method', prompt: 'facts', maxTokens: 2048 }), { text: '{}' });
  await assert.rejects(api.run({ id: 'oversized', prompt: 'facts', maxTokens: 99999 }), /unavailable/);
});

test('auxiliary reasoning opt-out is explicit, bounded and never enables tools or history', async () => {
  const seen = [];
  const analysis = new AnalysisCalls({ llm: { async *stream(options) {
    seen.push(options); yield { type: 'text-delta',text: '{}' }; yield { type: 'finish',reason: { kind: 'stop' } };
  } } });
  await analysis.run({ id: 'default',prompt: 'synthetic' });
  await analysis.run({ id: 'short',prompt: 'synthetic',reasoningEffort: 'off' });
  assert.equal(seen[0].reasoningEffort,undefined); assert.equal(seen[1].reasoningEffort,'off');
  for (const options of seen) { assert.deepEqual(options.tools,[]); assert.equal(options.messages.length,1); assert.equal(options.maxTokens,1024); }
  for (const params of [{ reasoningEffort: 'high' },{ maxTokens: 4096 },{ prompt: 'x'.repeat(7001) }]) {
    await assert.rejects(analysis.run({ id: 'invalid',prompt: 'synthetic',...params }),/Analysis unavailable/);
  }
  assert.equal(seen.length,2);
});

test('truncated auxiliary output is rejected and releases the current execution owner', async () => {
  let truncated = true;
  const analysis = new AnalysisCalls({ llm: { async *stream() {
    yield { type: 'text-delta',text: '{}' }; yield { type: 'finish',reason: { kind: truncated ? 'max-tokens' : 'stop' } };
  } } });
  await assert.rejects(analysis.run({ id: 'one',prompt: 'synthetic',reasoningEffort: 'off' }),/Analysis truncated/);
  truncated = false; assert.deepEqual(await analysis.run({ id: 'two',prompt: 'synthetic' }),{ text: '{}' });
});
