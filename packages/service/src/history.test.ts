import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatMessageSchema, ChatSessionSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { PetRepository } from './storage/pet.js';
import { ChatRepository } from './storage/chat.js';
import { HistorySearch } from './knowledge/history.js';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-history-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  const repo = new ChatRepository(store), pet = new PetRepository(store).getOrCreate();
  for (const id of ['one', 'two']) repo.saveSession(ChatSessionSchema.parse({ id, pet_id: pet.id }));
  const settings = { memory_session_search_default_scope: 'current_session',
    memory_session_search_max_result_chars: 1000, memory_session_search_total_budget_chars: 5000 };
  const search = new HistorySearch(store, () => settings);
  let counter = 0;
  const add = (content: string, session_id = 'one') => {
    const index = counter++;
    const message = ChatMessageSchema.parse({ id: `m${index}`, session_id, role: 'user', content,
      created_at: `2026-10-21T10:${String(index).padStart(2, '0')}:00` });
    repo.saveMessage(message); return message;
  };
  return { store, repo, settings, search, add,
    close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}

test('history repository matches content, isolates sessions and returns bounded newest-first results', async () => {
  const f = await fixture();
  try {
    f.add('Older Python note'); f.add('TypeScript project'); const newer = f.add('Newer Python note');
    assert.deepEqual(f.repo.search('Python').map(m => m.content), ['Newer Python note', 'Older Python note']);
    assert.deepEqual(f.repo.search('absent'), []);
    f.add('Python elsewhere', 'two');
    assert.deepEqual(f.repo.search('Python', 'one').map(m => m.id), [newer.id, 'm0']);
    for (let i = 0; i < 20; i++) f.add(`Python number ${i}`);
    assert.equal(f.repo.search('Python', undefined, 5).length, 5);
    assert.throws(() => f.repo.search('Python', undefined, 0));
    assert.throws(() => f.repo.search('Python', undefined, 1001));
  } finally { await f.close(); }
});

test('history search rejects blank queries and enforces configured cross-session access and result caps', async () => {
  const f = await fixture();
  try {
    const empty = f.search.search(' \n ', 'one'); assert.equal(empty.total_found, 0); assert.match(empty.note, /Empty query/);
    f.add('Chat one'); f.add('Chat two', 'two');
    assert.deepEqual(f.search.search('Chat', 'one').results.map(m => m.session_id), ['one']);
    const denied = f.search.search('Chat', 'one', 'all_sessions');
    assert.equal(denied.scope, 'current_session'); assert.equal(denied.total_shown, 1);
    f.settings.memory_session_search_default_scope = 'all_sessions';
    assert.equal(f.search.search('Chat', 'one', 'all_sessions').total_shown, 2);
    // Broad settings do not widen a request that omitted scope.
    assert.equal(f.search.search('Chat', 'one').total_shown, 1);
    for (let i = 0; i < 15; i++) f.add(`Zebra ${i}`);
    assert.equal(f.search.search('Zebra', 'one', 'current_session', 50).total_shown, 10);
    assert.equal(f.search.search('absent', 'one').total_found, 0);
  } finally { await f.close(); }
});

test('history excerpts use Unicode character limits and a hard total budget', async () => {
  const f = await fixture();
  try {
    f.add('关键词🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂');
    f.settings.memory_session_search_max_result_chars = 10;
    const clipped = f.search.search('关键词', 'one');
    assert.equal([...clipped.results[0]!.content].length, 13);
    assert.equal(clipped.results[0]!.content, '关键词🙂🙂🙂🙂🙂🙂🙂...');
    f.settings.memory_session_search_max_result_chars = 1000;
    f.settings.memory_session_search_total_budget_chars = 30;
    for (let i = 0; i < 5; i++) f.add(`Match keyword with a bit of content ${i}`);
    const bounded = f.search.search('keyword', 'one');
    assert.equal(bounded.budget_exhausted, true); assert.ok(bounded.total_shown < bounded.total_found);
    assert.ok(bounded.results.reduce((n, r) => n + [...r.content].length, 0) <= 30);
  } finally { await f.close(); }
});

test('history retrieval redacts secrets and excludes forgotten source messages from text and metadata', async () => {
  const f = await fixture();
  try {
    f.add('key sk-1234567890abcdef1234567890abcdef');
    f.add('Auth Bearer abc123def456ghi789jkl'); f.add('Email user@example.com');
    for (const [query, secret] of [['key', 'sk-'], ['Auth', 'Bearer'], ['Email', 'user@example.com']]) {
      const result = f.search.search(query!, 'one'); assert.equal(result.total_shown, 1);
      assert.ok(!result.results[0]!.content.includes(secret!)); assert.match(result.results[0]!.content, /REDACTED/);
    }
    const removed = f.add('remembered nickname'); f.add('remembered allowed');
    f.store.run('INSERT INTO relationship_barrier VALUES(?,?)', removed.id, '2026-10-21T12:00:00');
    const result = f.search.search('remembered', 'one');
    assert.equal(result.total_found, 1); assert.equal(result.total_shown, 1);
    assert.equal(result.results[0]!.content, 'remembered allowed');
    const markdown = f.search.markdown(result);
    assert.match(markdown, /Session Search Results/); assert.match(markdown, /remembered allowed/);
    assert.ok(!markdown.includes('nickname')); assert.match(f.search.markdown(f.search.search('absent', 'one')), /No results found/);
  } finally { await f.close(); }
});
