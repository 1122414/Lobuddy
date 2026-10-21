import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ConversationSummarySchema, MemoryItemSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { MemoryRepository } from './storage/memory.js';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-memory-repository-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  return { store, repo: new MemoryRepository(store), close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}
test('memory records preserve IDs, type, confidence, status and scope independently', async () => {
  const f = await fixture();
  try {
    const item = MemoryItemSchema.parse({ id: 'test-1', memory_type: 'user_profile', content: 'User likes Python', confidence: 0.9, priority: 85 });
    assert.equal(f.repo.save(item).id, item.id); assert.deepEqual(f.repo.get(item.id), item);
    f.repo.save(MemoryItemSchema.parse({ id: 'b', memory_type: 'user_profile', content: 'B', status: 'deprecated' }));
    f.repo.save(MemoryItemSchema.parse({ id: 'c', memory_type: 'system_profile', content: 'C' }));
    assert.equal(f.repo.list('user_profile').length, 2);
    assert.deepEqual(f.repo.list('user_profile', 'active').map(value => value.id), ['test-1']);
    assert.equal(f.repo.updateStatus('test-1', 'deprecated'), true);
    assert.equal(f.repo.get('test-1')!.status, 'deprecated');
    assert.equal(f.repo.updateStatus('missing', 'deprecated'), false);
    for (const scope of ['lobuddy', 'other']) f.repo.save(MemoryItemSchema.parse({ id: scope, memory_type: 'project_memory', scope, content: scope }));
    assert.deepEqual(f.repo.list('project_memory', undefined, 'lobuddy').map(value => value.id), ['lobuddy']);
    assert.equal(f.repo.delete('test-1'), true); assert.equal(f.repo.get('test-1'), undefined); assert.equal(f.repo.delete('test-1'), false);
  } finally { await f.close(); }
});
test('memory keyword lookup respects active status, title, type and result bounds', async () => {
  const f = await fixture();
  try {
    for (const [id, title, content, type] of [
      ['react', 'React', 'project setup', 'project_memory'],
      ['vue', 'Vue', 'Vue project setup', 'project_memory'],
      ['history', '', 'Used React before', 'episodic_memory'],
    ]) f.repo.save(MemoryItemSchema.parse({ id, title, content, memory_type: type }));
    assert.deepEqual(f.repo.search('React', 'project_memory').map(value => value.id), ['react']);
    assert.equal(f.repo.search('React').length, 2);
    assert.equal(f.repo.search('React', undefined, 1).length, 1);
    f.repo.updateStatus('react', 'deprecated'); assert.deepEqual(f.repo.search('React').map(value => value.id), ['history']);
    assert.throws(() => f.repo.search('React', undefined, 0));
    assert.throws(() => f.repo.list(undefined, undefined, undefined, 10001));
  } finally { await f.close(); }
});
test('conversation summaries retain session isolation, newest-first order and identity on update', async () => {
  const f = await fixture();
  try {
    const old = ConversationSummarySchema.parse({ id: 's1', session_id: 'session-1', summary_type: 'rolling', content: 'User asked about Python', created_at: '2026-10-01T00:00:00' });
    f.repo.saveSummary(old); assert.equal(f.repo.summaries('session-1')[0]!.content, old.content);
    f.repo.saveSummary(ConversationSummarySchema.parse({ ...old, id: 's2', content: 'B', created_at: '2026-10-02T00:00:00' }));
    f.repo.saveSummary(ConversationSummarySchema.parse({ ...old, id: 'other', session_id: 'other' }));
    assert.deepEqual(f.repo.summaries('session-1').map(value => value.id), ['s2', 's1']);
    assert.deepEqual(f.repo.summaries('session-1', 1).map(value => value.content), ['B']);
    f.repo.saveSummary({ ...old, content: 'Updated' });
    assert.equal(f.repo.summaries('session-1').length, 2); assert.equal(f.repo.summaries('session-1')[1]!.content, 'Updated');
    assert.deepEqual(f.repo.summaries('unknown'), []); assert.throws(() => f.repo.summaries('session-1', 0));
  } finally { await f.close(); }
});
