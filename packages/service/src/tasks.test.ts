import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, readFile, lstat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { ChatSessionSchema, TurnSendSchema, type BridgeEvent, type TurnState } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { runtimeSettings } from './config/settings.js';
import { TaskCoordinator } from './tasks/coordinator.js';
import { ImageStore } from './tools/images.js';
import type { Engine } from './engine/runtime.js';
import { Approvals } from './tasks/approvals.js';
import { TurnStateSchema } from '@lobuddy/contracts';

class FakeEngine implements Engine {
  connected = false; closed = false; sequence = 0; readonly turns: Record<string, unknown>[] = [];
  readonly resolved: Record<string, unknown>[] = [];
  private buffer: BridgeEvent[] = []; private wake?: () => void;
  async start() {}
  async call(method: string, params: Record<string, unknown>) {
    if (method === 'turn.send') {
      assert.notEqual(params.context, '', 'Bridge text validator rejects an explicitly empty context');
      this.turns.push(params); this.emit(params, 'turn.started');
    }
    if (method === 'turn.cancel') {
      const turn = this.turns.find(item => item.turnId === params.turnId);
      if (turn) { this.emit(turn, 'text.delta', { text: '迟到内容' }); this.emit(turn, 'turn.cancelled'); }
    }
    if (method === 'tool.resolve') this.resolved.push(params);
    return {};
  }
  emit(turn: Record<string, unknown>, kind: BridgeEvent['kind'], data: BridgeEvent['data'] = {}) {
    this.buffer.push({ sessionId: String(turn.sessionId), taskId: String(turn.taskId), turnId: String(turn.turnId), sequence: ++this.sequence, kind, data }); this.wake?.();
  }
  async *events(ready?: () => void) {
    this.connected = true; ready?.();
    while (!this.closed) {
      if (this.buffer.length) yield this.buffer.shift()!;
      else await new Promise<void>(resolve => { this.wake = resolve; });
    }
    this.connected = false;
  }
  async close() { this.closed = true; this.connected = false; this.wake?.(); }
}
async function until(check: () => boolean, max = 4000) {
  const start = Date.now(); while (!check()) { if (Date.now() - start > max) throw Error('condition timed out'); await delay(5); }
}
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-tasks-')), workspace = join(root, 'workspace'), data = join(root, 'data');
  await mkdir(workspace); await mkdir(data);
  const store = new Store(join(data, 'lobuddy.db'), { create: true });
  const chat = new ChatRepository(store); for (const id of ['one','two']) chat.saveSession(ChatSessionSchema.parse({ id }));
  const settings = runtimeSettings({ data, workspace, logs: join(root, 'logs') });
  const engines: FakeEngine[] = [], events: string[] = [];
  const coordinator = new TaskCoordinator({ store, settings: () => settings, engine: () => { const engine = new FakeEngine(); engines.push(engine); return engine; },
    images: new ImageStore(join(data, 'images')), applicationRoot: join(root, 'application'), publish: event => { events.push(event.kind); } });
  const submit = (id: string, session_id = 'one', lane: TurnState['lane'] = 'foreground') => coordinator.submit(id, TurnSendSchema.parse({ session_id, text: '测试', lane }));
  return { root, workspace, store, engines, events, coordinator, settings, submit, clean: async () => { await coordinator.close(); store.close(); await rm(root, { recursive: true, force: true }); } };
}
test('approval timeout, wrong identity and expired owner reject instead of granting execution', async () => {
  const approvals = new Approvals(() => {});
  const state = TurnStateSchema.parse({ turn_id: 't', task_id: 'task', session_id: 's', engine_id: 'engine', input_text: 'test', lane: 'foreground', status: 'running' });
  const signal = new AbortController().signal;
  const timeout = approvals.request(state, 'write', 'file', 'check', 5, signal, () => true);
  assert.equal(approvals.resolve('wrong-id', true), false); assert.equal(await timeout, false); assert.deepEqual(approvals.list(), []);
  let active = true;
  const expired = approvals.request(state, 'write', 'file', 'check', 5, signal, () => active);
  active = false; assert.equal(approvals.resolve(approvals.list()[0]!.approval_id, true), false); assert.equal(await expired, false);
});
test('each lane is FIFO and cancelling foreground preserves background and excludes late text', async () => {
  const f = await fixture();
  try {
    const first = await f.submit('first'), second = await f.submit('second'), background = await f.submit('background', 'two', 'background');
    await until(() => f.engines[0]?.turns.length === 2);
    const engine = f.engines[0]!;
    assert.deepEqual(new Set(engine.turns.map(turn => turn.turnId)), new Set([first.turn_id, background.turn_id]));
    await f.coordinator.cancel(first.turn_id);
    await until(() => engine.turns.length === 3);
    assert.equal(f.coordinator.turns.get(first.turn_id).status, 'cancelled');
    assert.equal(f.coordinator.turns.get(first.turn_id).output_text, '');
    assert.equal(f.coordinator.turns.get(background.turn_id).status, 'running');
    for (const turn of engine.turns.filter(item => item.turnId !== first.turn_id)) {
      engine.emit(turn, 'text.final', { text: String(turn.turnId) }); engine.emit(turn, 'turn.completed');
    }
    await until(() => !f.coordinator.busy);
    assert.equal(f.coordinator.turns.get(second.turn_id).output_text, second.turn_id);
    assert.equal(f.coordinator.turns.get(background.turn_id).output_text, background.turn_id);
    assert.equal(f.coordinator.ledger.summary().pet.exp, 10);
  } finally { await f.clean(); }
});
test('approval rejection and owner closure have no file effect, approval executes once', async () => {
  const f = await fixture();
  try {
    await f.submit('write'); await until(() => f.engines[0]?.turns.length === 1);
    const engine = f.engines[0]!, turn = engine.turns[0]!;
    engine.emit(turn, 'tool.request', { callId: 'denied', name: 'lobuddy_write_file', arguments: { path: 'denied.txt', content: 'no' } });
    await until(() => f.coordinator.approvals.list().length === 1);
    assert.equal(f.coordinator.approvals.resolve(f.coordinator.approvals.list()[0]!.approval_id, false), true);
    await until(() => engine.resolved.length === 1); await assert.rejects(lstat(join(f.workspace, 'denied.txt')), { code: 'ENOENT' });
    engine.emit(turn, 'tool.request', { callId: 'allowed', name: 'lobuddy_write_file', arguments: { path: 'allowed.txt', content: 'yes' } });
    await until(() => f.coordinator.approvals.list().length === 1);
    f.coordinator.approvals.resolve(f.coordinator.approvals.list()[0]!.approval_id, true);
    await until(() => engine.resolved.length === 2); assert.equal(await readFile(join(f.workspace, 'allowed.txt'), 'utf8'), 'yes');
    engine.emit(turn, 'tool.request', { callId: 'allowed', name: 'lobuddy_write_file', arguments: { path: 'allowed.txt', content: 'changed' } });
    await until(() => engine.resolved.length === 3); assert.equal(engine.resolved[2]!.ok, false);
    engine.emit(turn, 'tool.request', { callId: 'closing', name: 'lobuddy_write_file', arguments: { path: 'closing.txt', content: 'no' } });
    await until(() => f.coordinator.approvals.list().length === 1); await f.coordinator.close();
    await assert.rejects(lstat(join(f.workspace, 'closing.txt')), { code: 'ENOENT' }); assert.deepEqual(f.coordinator.approvals.list(), []);
  } finally { await f.clean(); }
});
test('timeout remains failed and engine stream loss never replays a durable request', async () => {
  const f = await fixture();
  try {
    f.settings.task_timeout = 1;
    const timeout = await f.submit('timeout'); await until(() => !f.coordinator.busy);
    assert.equal(f.coordinator.turns.get(timeout.turn_id).status, 'failed');
    assert.match(f.coordinator.turns.get(timeout.turn_id).error, /超过设定时限/); assert.equal(f.coordinator.ledger.summary().pet.exp, 0);
    const crash = await f.submit('crash'); await until(() => f.engines[0]!.turns.length === 2);
    f.engines[0]!.emit(f.engines[0]!.turns[1]!, 'tool.request', { callId: 'pending-at-crash', name: 'lobuddy_write_file', arguments: { path: 'crash.txt', content: 'must not write' } });
    await until(() => f.coordinator.approvals.list().length === 1);
    await f.engines[0]!.close(); await until(() => !f.coordinator.busy);
    assert.equal(f.coordinator.turns.get(crash.turn_id).status, 'failed');
    assert.deepEqual(f.coordinator.approvals.list(), []); await assert.rejects(lstat(join(f.workspace, 'crash.txt')), { code: 'ENOENT' });
    assert.equal((await f.submit('crash')).turn_id, crash.turn_id); assert.equal(f.engines.length, 1);
    const fresh = await f.submit('fresh'); assert.notEqual(fresh.engine_id, crash.engine_id);
    await until(() => f.engines.length === 2 && f.engines[1]!.turns.length === 1);
    assert.equal(f.engines[1]!.turns.length, 1);
  } finally { await f.clean(); }
});
