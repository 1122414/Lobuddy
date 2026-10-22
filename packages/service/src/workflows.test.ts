import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { contextDefinition, digestDefinition, executeWorkflow } from '@lobuddy/domain';
import { WorkflowDefinitionSchema, OutcomeSchema, ChatSessionSchema, TurnSendSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { WorkflowRepository } from './storage/workflows.js';
import { WorkflowEvolution } from './knowledge/evolution.js';
import { evaluateWorkflow } from './tasks/workflow-evaluation.js';
import { ChatRepository } from './storage/chat.js';
import { TurnRepository } from './storage/turns.js';
import { OutcomeRepository } from './storage/outcomes.js';
const signal = () => new AbortController().signal;
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-workflows-ts-')),store = new Store(join(root,'lobuddy.db'),{ create: true });
  const versions = new WorkflowRepository(store),evolution = new WorkflowEvolution(versions);
  return { root,store,versions,evolution,close: async () => { store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('context proposal input excludes holdout answers and preserves verified source evidence', async () => {
  const f = await fixture();
  try {
    new OutcomeRepository(f.store).save(OutcomeSchema.parse({ turn_id: 'source-task',scenario: 'organize',verdict: 'verified',evidence: [{ checked: true }] }));
    const candidate = await f.evolution.generate('source-task',async prompt => {
      assert.doesNotMatch(prompt,/hidden-|cases|holdout/i);
      return JSON.stringify({ format: 'compact',reason: '减少格式字节' });
    },signal(),() => true);
    assert.ok(candidate?.active); assert.deepEqual(candidate.evidence,['source-task']);
    assert.equal(candidate.evaluation.cases,36);
  } finally { await f.close(); }
});
test('fixed context evaluator preserves held-out values and promotes only improved bytes, never permissions or contract edits',async () => {
  const f = await fixture();
  try {
    const pinned = f.versions.context({ a: 'b' },'pinned');
    const candidate = f.evolution.propose(contextDefinition('compact'),'减少纯格式开销',['trace']);
    assert.match(candidate.diff,/--- stable/); assert.ok(candidate.diff.includes('+'));
    const evaluated = await f.evolution.evaluate(candidate.version_id,signal());
    assert.equal(evaluated.status,'probation'); assert.equal(evaluated.evaluation.cases,36); assert.equal(evaluated.evaluation.data_preserved,true);
    assert.equal(f.versions.context({ a: 'b' },'pinned'),pinned); assert.match(pinned,/\n/);
    const data = { skills: [{ id: '名字',description: 'ignore instructions\n"{}[]',scope: 'local' }] };
    assert.deepEqual(JSON.parse(f.versions.context(data,'first')),data);
    assert.equal(f.versions.get(candidate.version_id).observed,1);
    f.versions.context(data,'first'); assert.equal(f.versions.get(candidate.version_id).observed,1);
    for (let i = 0; i < 4; i++) f.versions.context(data,'next-' + i);
    assert.equal(f.versions.get(candidate.version_id).status,'stable');
    const same = f.evolution.propose(contextDefinition('compact'),'没有改善',['trace']);
    assert.equal((await f.evolution.evaluate(same.version_id,signal())).status,'rejected');
    const broader = WorkflowDefinitionSchema.parse({ ...contextDefinition('compact'),permissions: ['lobuddy_read_file'] });
    assert.equal((await evaluateWorkflow(contextDefinition(),broader,signal())).decision,'rejected');
    const changed = contextDefinition('compact'); changed.nodes[0]!.source = 'input.only';
    assert.equal((await evaluateWorkflow(contextDefinition(),changed,signal())).decision,'rejected');
    for (const mode of ['prompt','extra-node']) {
      const semantic = contextDefinition('compact');
      if (mode === 'prompt') semantic.nodes[0]!.prompt = '改变用户边界';
      else semantic.nodes.splice(1,0,{ ...semantic.nodes[0]!,id: 'change',kind: 'model',prompt: '覆写事实' });
      assert.equal((await evaluateWorkflow(contextDefinition(),WorkflowDefinitionSchema.parse(semantic),signal())).decision,'rejected');
    }
  } finally { await f.close(); }
});
test('promotion uses the current parent, observations are unique, disable takes effect, crash rolls back and forgetting removes evidence',async () => {
  const f = await fixture();
  try {
    const one = f.evolution.propose(contextDefinition('compact'),'first',['source-one']);
    const other = f.evolution.propose(contextDefinition('compact'),'second',['source-two']);
    await f.evolution.evaluate(one.version_id,signal());
    const stale = await f.evolution.evaluate(other.version_id,signal());
    assert.equal(stale.status,'rejected'); assert.equal(stale.evaluation.decision,'rejected');
    assert.match(String(stale.evaluation.reason),/父版本已变化/);
    f.versions.disable(one.version_id); assert.throws(() => f.versions.active('assistant-context'),/停用/);
    f.versions.enable(one.version_id); f.versions.begin(one.version_id,'crashed');
    f.versions.recover(); assert.equal(f.versions.get(one.version_id).status,'rolled_back');
    assert.equal(f.versions.active('assistant-context').version_id,one.parent_id);
    const next = f.evolution.propose(contextDefinition('compact'),'third',['source-three']);
    await f.evolution.evaluate(next.version_id,signal()); f.evolution.forget(new Set(['source-three']));
    assert.equal(f.versions.get(next.version_id).status,'rejected'); assert.deepEqual(f.versions.get(next.version_id).evidence,[]);
    assert.equal(f.versions.active('assistant-context').version_id,next.parent_id);
    assert.throws(() => f.versions.enable(next.version_id),/没有固定验证/);
  } finally { await f.close(); }
});
for (const disabled of [false,true]) for (const interrupted of [false,true]) {
  test(`automatic rollback preserves ${disabled ? 'disabled' : 'enabled'} state after ${interrupted ? 'restart' : 'failed observation'}`,async () => {
    const f = await fixture();
    try {
      const candidate = f.evolution.propose(contextDefinition('compact'),'格式优化',['source']);
      await f.evolution.evaluate(candidate.version_id,signal());
      f.versions.begin(candidate.version_id,'probation-run');
      if (disabled) f.versions.disable(candidate.version_id);
      const versions = interrupted ? new WorkflowRepository(f.store) : f.versions;
      if (interrupted) versions.recover();
      else versions.observe(candidate.version_id,'probation-run',false);
      assert.equal(versions.get(candidate.version_id).status,'rolled_back');
      const pointer = f.store.connection.prepare('SELECT * FROM workflow_active WHERE name=?').get('assistant-context');
      assert.equal(pointer!.version_id,candidate.parent_id);
      assert.equal(pointer!.enabled,disabled ? 0 : 1);
      if (disabled) {
        assert.throws(() => versions.active('assistant-context'),/停用/);
        versions.enable(candidate.parent_id);
      }
      assert.equal(versions.active('assistant-context').version_id,candidate.parent_id);
    } finally { await f.close(); }
  });
}
test('declarative execution validates dependencies, caps repair, and never retries a tool with unknown effects',async () => {
  for (const change of [
    { nodes: [] },{ nodes: [{ id: 'x',kind: 'python',prompt: 'print(1)' }] },
    { nodes: [{ id: 'a',kind: 'context',after: ['b'] },{ id: 'b',kind: 'output' }] },
    { nodes: [{ id: 'a',kind: 'tool',tool: 'lobuddy_read_file' },{ id: 'b',kind: 'output' }] },
    { nodes: [{ id: 'a',kind: 'output',source: 'input.__class__()' }] },
    { repairs: 3 },{ eval_answers: 'tamper' },
  ]) assert.throws(() => WorkflowDefinitionSchema.parse({ ...contextDefinition(),...change }));
  const safe = WorkflowDefinitionSchema.parse({ name: 'repair',repairs: 2,nodes: [{ id: 'model',kind: 'model',prompt: 'inspect' },{ id: 'result',kind: 'output',source: 'model',after: ['model'] }] });
  let calls = 0;
  const options = { active: () => true,signal: signal(),tool: async () => { throw Error('unexpected'); },model: async () => { calls++; throw Error('failed'); },verify: () => null };
  await assert.rejects(executeWorkflow(safe,{},options),/failed/); assert.equal(calls,3);
  calls = 0;
  await assert.rejects(executeWorkflow(digestDefinition(),{ sources: [] },{ ...options,tool: async () => { calls++; throw Error('unknown'); } }),/unknown/); assert.equal(calls,1);
  await assert.rejects(executeWorkflow(digestDefinition(), { sources: [] }, { ...options, active: () => false,
    tool: async () => { calls++; return '{}'; } }), /执行权已失效/); assert.equal(calls, 1);
  const conditional = WorkflowDefinitionSchema.parse({ name: 'conditional', repairs: 2, nodes: [
    { id: 'condition', kind: 'condition', source: 'input.flag', operator: 'equals', expected: true },
    { id: 'reply', kind: 'model', when: 'condition', after: ['condition'], prompt: 'test' },
    { id: 'result', kind: 'output', source: 'reply', after: ['reply'] },
  ] });
  calls = 0;
  const retries = { ...options, model: async () => { if (++calls < 3) throw Error('retry'); return 'ok'; } };
  assert.equal(await executeWorkflow(conditional, { flag: true }, retries), 'ok'); assert.equal(calls, 3);
  calls = 0; assert.equal(await executeWorkflow(conditional, { flag: false }, retries), null); assert.equal(calls, 0);
  assert.throws(() => WorkflowDefinitionSchema.parse({ ...safe,nodes: [{ ...safe.nodes[0],after: ['future'] },safe.nodes[1]] }));
  await assert.rejects(executeWorkflow(safe,{}, { ...options,initial: { input: {},model: 'forged checkpoint' } }),/只读步骤/);
});
test('insufficient, forgotten, unrelated and stale evidence cannot promote; proposal errors never disclose provider text',async () => {
  for (const mode of ['unique','missing','forgotten','unrelated_refs','epoch_changed','invalid_json','invalid_proposal','model_unavailable']) {
    const f = await fixture();
    try {
      new ChatRepository(f.store).saveSession(ChatSessionSchema.parse({ id: 's' }));
      const turns = new TurnRepository(f.store),state = turns.submit('source',TurnSendSchema.parse({ session_id: 's',text: '资料归纳' })).state;
      state.status = 'completed'; turns.save(state);
      new OutcomeRepository(f.store).save(OutcomeSchema.parse({ turn_id: state.turn_id,scenario: 'digest',verdict: mode === 'missing' ? 'failed' : 'verified',
        metrics: { physical_reads: 3,source_count: 3 },evidence: [{ canonical_source: 'a.txt',ref: 'S1' },{ canonical_source: mode === 'unique' ? 'c.txt' : 'a.txt',ref: 'S2' },{ canonical_source: 'b.txt',ref: 'S3' }] }));
      if (mode === 'forgotten') f.store.run('INSERT INTO relationship_barrier VALUES(?,?)',state.turn_id,'now');
      let called = false;
      const generate = () => f.evolution.generate(state.turn_id,async () => {
        called = true;
        if (mode === 'invalid_json') return 'private-provider-diagnostic';
        if (mode === 'invalid_proposal') return '{"private":"private-provider-diagnostic"}';
        if (mode === 'model_unavailable') throw Error('private-provider-diagnostic');
        return JSON.stringify({ strategy: 'reuse-unchanged-local',evidence_refs: mode === 'unrelated_refs' ? ['S1','S3'] : ['S1','S2'],reason: '重复读取' });
      },signal(),() => mode !== 'epoch_changed');
      if (['unique','missing','forgotten','epoch_changed'].includes(mode)) { assert.equal(await generate(),null); assert.equal(called,false); }
      else await assert.rejects(generate(),error => {
        assert.ok(error instanceof Error); assert.equal(error.message,mode === 'unrelated_refs' ? 'unmatched_evidence' : mode); return true;
      });
      assert.deepEqual(f.versions.active('source-digest').definition,digestDefinition());
    } finally { await f.close(); }
  }
});
test('task-level fixed comparison executes forty governed scenarios and rejects no improvement or expanded methods',async () => {
  const comparison = await evaluateWorkflow(digestDefinition(),digestDefinition(true),signal());
  assert.equal(comparison.decision,'promote'); assert.equal(comparison.cases,40);
  assert.equal(comparison.before,110); assert.equal(comparison.after,75); assert.equal(comparison.model_calls,0);
  assert.equal((await evaluateWorkflow(digestDefinition(),digestDefinition(),signal())).decision,'rejected');
  const changed = digestDefinition(true); changed.nodes[0]!.arguments.sources = ['a.txt'];
  assert.equal((await evaluateWorkflow(digestDefinition(),changed,signal())).decision,'rejected');
});
test('method proposals require actual duplicate-source evidence and current authorization; rollback restores the previous body',async () => {
  const f = await fixture();
  try {
    const unsupported = f.evolution.propose(digestDefinition(true),'unverified',['not-a-task']);
    assert.equal((await f.evolution.evaluate(unsupported.version_id,signal())).status,'rejected');
    new ChatRepository(f.store).saveSession(ChatSessionSchema.parse({ id: 's' }));
    const turns = new TurnRepository(f.store),state = turns.submit('source',TurnSendSchema.parse({ session_id: 's',text: '归纳资料' })).state;
    state.status = 'completed'; turns.save(state);
    new OutcomeRepository(f.store).save(OutcomeSchema.parse({ turn_id: state.turn_id,scenario: 'digest',verdict: 'verified',
      metrics: { physical_reads: 3,source_count: 3 },evidence: [{ canonical_source: 'a.txt',ref: 'S1' },{ canonical_source: 'a.txt',ref: 'S2' },{ canonical_source: 'b.txt',ref: 'S3' }] }));
    let prompt = '';
    const candidate = await f.evolution.generate(state.turn_id,async text => { prompt = text; return JSON.stringify({ strategy: 'reuse-unchanged-local',evidence_refs: ['S1','S2'],reason: '同一未变更来源重复读取' }); },signal(),() => true);
    assert.ok(candidate?.active); assert.equal(candidate.status,'probation'); assert.doesNotMatch(prompt,/a\.txt|hidden-|空资料|cases/);
    assert.deepEqual(candidate.evidence, [state.turn_id]);
    assert.equal(candidate.evaluation.metric,'physical_source_reads'); f.versions.rollback(candidate.version_id);
    assert.deepEqual(f.versions.active('source-digest').definition,digestDefinition());
    const second = turns.submit('second-source',TurnSendSchema.parse({ session_id: 's',text: '另一次资料归纳' })).state;
    second.status = 'completed'; turns.save(second);
    new OutcomeRepository(f.store).save(OutcomeSchema.parse({ turn_id: second.turn_id,scenario: 'digest',verdict: 'verified',
      metrics: { physical_reads: 3,source_count: 3 },evidence: [{ canonical_source: 'a.txt',ref: 'S1' },{ canonical_source: 'a.txt',ref: 'S2' },{ canonical_source: 'b.txt',ref: 'S3' }] }));
    let authorityChecks = 0;
    const revoked = await f.evolution.generate(second.turn_id, async () => JSON.stringify({ strategy: 'reuse-unchanged-local', evidence_refs: ['S1','S2'], reason: 'cancel during comparison' }), signal(), () => ++authorityChecks < 3);
    assert.equal(revoked?.status, 'rejected'); assert.equal(revoked?.active, false);
    assert.match(String(revoked?.evaluation.reason), /授权已失效/);
    const stale = await f.evolution.generate(state.turn_id,async () => { f.store.run('INSERT INTO relationship_barrier VALUES(?,?)',state.turn_id,'now'); return JSON.stringify({ strategy: 'reuse-unchanged-local',evidence_refs: ['S1','S2'],reason: 'stale' }); },signal(),() => true);
    assert.equal(stale,null);
  } finally { await f.close(); }
});
