import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { requestSchemas, responseSchemas, type Method, WorkflowDefinitionSchema, RepeatRuleSchema,
  SourceShareSchema, DelegationSpecSchema, ServerFrameSchema } from './index.js';

test('all 110 methods preserve 988 frozen Pydantic input outcomes and defaults', async () => {
  const samples = JSON.parse(await readFile(new URL('../../../migration/baseline/cases.json', import.meta.url), 'utf8')) as {
    id: string; method: Method; input: unknown; accepted: boolean; result?: unknown }[];
  assert.equal(new Set(samples.map(sample => sample.method)).size, 110);
  assert.deepEqual(Object.keys(requestSchemas).filter(method => !samples.some(sample => sample.method === method)), ['companionship.accept']);
  assert.equal(Object.keys(requestSchemas).length, 111);
  assert.deepEqual(Object.keys(responseSchemas).sort(), Object.keys(requestSchemas).sort());
  assert.equal(samples.length, 988);
  for (const sample of samples) {
    const result = requestSchemas[sample.method].safeParse(sample.input);
    assert.equal(result.success, sample.accepted, sample.id);
    if (result.success) assert.deepEqual(result.data, sample.result, sample.id);
  }
});

test('explicit handoff accepts only a bounded notice and optional session identity', () => {
  const parse = requestSchemas['companionship.accept'];
  assert.deepEqual(parse.parse({ notice_id: 'shown' }), { notice_id: 'shown', session_id: '' });
  for (const bad of [{}, { notice_id: '' }, { notice_id: 'x'.repeat(129) }, { notice_id: 'shown', text: 'forged' },
    { notice_id: 'shown', session_id: 1 }]) assert.equal(parse.safeParse(bad).success, false);
});

test('historical unsafe workflow graphs remain rejected', () => {
  const original = { name: 'synthetic', nodes: [{ id: 'result', kind: 'output' }] };
  for (const change of [{ nodes: [] }, { nodes: [{ id: 'x', kind: 'python', prompt: 'print(1)' }] },
    { nodes: [{ id: 'a', kind: 'context', after: ['b'] }, { id: 'b', kind: 'output' }] },
    { nodes: [{ id: 'a', kind: 'tool', tool: 'lobuddy_read_file' }, { id: 'b', kind: 'output' }] },
    { nodes: [{ id: 'a', kind: 'output', source: 'input.__class__()' }] }, { repairs: 3 }, { eval_answers: 'tamper' }]) {
    assert.equal(WorkflowDefinitionSchema.safeParse({ ...original, ...change }).success, false);
  }
});

test('historical invalid repeat rules, source scope and explicit acceptance are enforced', () => {
  for (const bad of [{ frequency: 'cron' }, { frequency: 'daily' }, { frequency: 'daily', local_time: '25:00' },
    { frequency: 'weekly', local_time: '09:00' }, { frequency: 'weekly', local_time: '09:00', weekdays: [7] },
    { frequency: 'weekly', local_time: '09:00', weekdays: [1, 1] }, { frequency: 'once', weekdays: [1] }, { end_at: Infinity }]) {
    assert.equal(RepeatRuleSchema.safeParse(bad).success, false);
  }
  assert.equal(SourceShareSchema.safeParse({ title: 'x', text: 'x', project_id: 'p', session_id: 's' }).success, false);
  assert.equal(DelegationSpecSchema.safeParse({ goal: 'x', criteria: ['模型自称完成'], wait: { kind: 'user' } }).success, false);
});

test('Unicode boundaries count code points and unsafe integer loss is rejected', () => {
  assert.equal(requestSchemas['session.create'].safeParse({ title: '😀'.repeat(100) }).success, true);
  assert.equal(requestSchemas['session.create'].safeParse({ title: '😀'.repeat(101) }).success, false);
  assert.equal(requestSchemas['project.bind'].safeParse({ session_id: 's', revision: Number.MAX_SAFE_INTEGER + 1 }).success, false);
  const result = DelegationSpecSchema.parse({ goal: '\u0085hello\u0085', criteria: ['通知按规则投递（不代表已读）'], wait: { kind: 'user' } });
  assert.equal(result.goal, 'hello');
});

test('mismatched protocol and malformed outgoing values cannot cross the boundary', () => {
  assert.equal(ServerFrameSchema.safeParse({ kind: 'ready', protocol: 1 }).success, false);
  assert.equal(responseSchemas['approval.resolve'].safeParse({ accepted: 'yes' }).success, false);
  assert.equal(responseSchemas['service.health'].safeParse({ protocol: 2 }).success, false);
});
