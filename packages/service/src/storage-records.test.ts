import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatSessionSchema, ChatMessageSchema, TurnSendSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { PetRepository } from './storage/pet.js';
import { ChatRepository } from './storage/chat.js';
import { Preferences } from './storage/preferences.js';
import { TurnRepository } from './storage/turns.js';
import { RuntimeLedger } from './storage/ledger.js';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-storage-records-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  return { store, close: async () => { store.close(); await rm(root, { recursive: true, force: true }); } };
}
test('initialized storage retains base tables, custom pet IDs and update identity', async () => {
  const f = await fixture();
  try {
    const tables = new Set(f.store.connection.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(row => row.name));
    for (const name of ['pet_state', 'task_record', 'task_result', 'app_settings']) assert.ok(tables.has(name));
    const repo = new PetRepository(f.store), pet = repo.getOrCreate();
    assert.equal(pet.name, 'Lobuddy'); assert.equal(pet.level, 1); assert.deepEqual(repo.get(), pet);
    repo.save({ ...pet, level: 5, exp: 100 }); assert.equal(repo.get()!.level, 5); assert.equal(repo.get()!.exp, 100);
    const custom = repo.getOrCreate('new_pet'); assert.equal(custom.name, 'Lobuddy'); assert.deepEqual(repo.getOrCreate('new_pet'), custom);
    assert.equal(repo.get('missing'), undefined);
  } finally { await f.close(); }
});
test('preferences preserve strings and JSON, missing values and one row per key', async () => {
  const f = await fixture();
  try {
    const repo = new Preferences(f.store);
    assert.equal(repo.get('missing'), undefined); assert.deepEqual(repo.json('missing'), {});
    repo.set('test_key', 'test_value'); assert.equal(repo.get('test_key'), 'test_value');
    repo.set('test_key', 'updated'); assert.equal(repo.get('test_key'), 'updated');
    repo.set('json_key', JSON.stringify({ key: 'value', number: 42 }));
    assert.deepEqual(repo.json('json_key'), { key: 'value', number: 42 });
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM app_settings').get()!.n, 2);
  } finally { await f.close(); }
});
test('foreign keys cascade chat messages and settled results without orphan records', async () => {
  const f = await fixture();
  try {
    const chat = new ChatRepository(f.store); chat.saveSession(ChatSessionSchema.parse({ id: 'session' }));
    for (const role of ['user', 'assistant']) chat.saveMessage(ChatMessageSchema.parse({ id: role, role, session_id: 'session', content: role }));
    assert.equal(chat.messages('session').length, 2);
    f.store.run('DELETE FROM chat_session WHERE id=?', 'session'); assert.equal(chat.messages('session').length, 0);
    chat.saveSession(ChatSessionSchema.parse({ id: 'task-session' }));
    const turns = new TurnRepository(f.store), ledger = new RuntimeLedger(f.store, turns);
    const turn = turns.submit('request', TurnSendSchema.parse({ session_id: 'task-session', text: 'Test' })).state;
    turn.status = 'completed'; turn.output_text = 'Full output'; ledger.finish(turn);
    assert.ok(f.store.connection.prepare('SELECT 1 FROM task_result WHERE task_id=?').get(turn.task_id));
    f.store.run('DELETE FROM task_record WHERE id=?', turn.task_id);
    assert.equal(f.store.connection.prepare('SELECT 1 FROM task_result WHERE task_id=?').get(turn.task_id), undefined);
  } finally { await f.close(); }
});
