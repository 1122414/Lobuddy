import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { contextDefinition } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { WorkflowRepository } from './storage/workflows.js';
import { WorkflowEvolution } from './knowledge/evolution.js';

test('a comparison against an obsolete parent is rejected with evidence, never recorded as a promotion', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-promotion-parent-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  try {
    const repo = new WorkflowRepository(store), evolution = new WorkflowEvolution(repo);
    const first = evolution.propose(contextDefinition('compact'), 'first', ['trace-one']);
    const second = evolution.propose(contextDefinition('compact'), 'second', ['trace-two']);
    await evolution.evaluate(first.version_id, new AbortController().signal);
    const rejected = await evolution.evaluate(second.version_id, new AbortController().signal);
    assert.equal(rejected.status, 'rejected');
    assert.equal(rejected.evaluation.decision, 'rejected');
    assert.match(String(rejected.evaluation.reason), /父版本.*重新提议/);
    assert.equal(rejected.evaluation.cases, 36);
    assert.ok(Number(rejected.evaluation.before) > Number(rejected.evaluation.after));
    assert.equal(repo.active('assistant-context').version_id, first.version_id);
    assert.deepEqual(await evolution.evaluate(second.version_id, new AbortController().signal), rejected);
  } finally { store.close(); await rm(root, { recursive: true, force: true }); }
});

test('disabled parent rejects promotion and failed activation rolls back its evaluation record atomically', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-promotion-atomic-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  try {
    const repo = new WorkflowRepository(store), evolution = new WorkflowEvolution(repo);
    const candidate = evolution.propose(contextDefinition('compact'), 'candidate', ['trace']);
    const pending = evolution.evaluate(candidate.version_id, new AbortController().signal);
    repo.disable(candidate.parent_id);
    const rejected = await pending;
    assert.equal(rejected.status, 'rejected');
    assert.throws(() => repo.active('assistant-context'), /停用/);
    repo.enable(candidate.parent_id);
    const next = evolution.propose(contextDefinition('compact'), 'atomic candidate', ['trace-new']);
    store.run("CREATE TRIGGER fail_promotion BEFORE UPDATE OF version_id ON workflow_active BEGIN SELECT RAISE(ABORT, 'activation fault'); END");
    await assert.rejects(evolution.evaluate(next.version_id, new AbortController().signal), /activation fault/);
    assert.equal(repo.get(next.version_id).status, 'candidate');
    assert.deepEqual(repo.get(next.version_id).evaluation, {});
    assert.equal(repo.active('assistant-context').version_id, candidate.parent_id);
    store.run('DROP TRIGGER fail_promotion');
    assert.equal((await evolution.evaluate(next.version_id, new AbortController().signal)).status, 'probation');
  } finally { store.close(); await rm(root, { recursive: true, force: true }); }
});
