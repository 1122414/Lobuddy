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
import sharp from 'sharp';

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
test('image references persist once, stay attached to their owning turn and do not leak into subsequent text turns', async () => {
  const f = await fixture();
  try {
    const images = new ImageStore(join(f.root,'data/images'));
    const png = await sharp({ create: { width: 60,height: 30,channels: 3,background: 'red' } }).png().toBuffer();
    const image = await images.importBytes(png,'.png');
    const params = TurnSendSchema.parse({ session_id: 'one',text: '看看',image_id: image.image_id });
    const turn = await f.coordinator.submit('image-request',params);
    assert.equal((await f.coordinator.submit('image-request',params)).turn_id,turn.turn_id);
    await until(() => Boolean(f.engines[0]?.turns.length));
    const engine = f.engines[0]!, dispatched = engine.turns[0]!;
    assert.equal(f.coordinator.turns.get(turn.turn_id).image_id,image.image_id);
    assert.equal(f.store.connection.prepare('SELECT image_path FROM chat_message WHERE id=?').get(turn.turn_id)?.image_path,image.image_id);
    assert.deepEqual(dispatched.image,{ image_id: image.image_id,media_type: 'image/png',width: 60,height: 30 });
    await f.coordinator.cancel(turn.turn_id);
    const next = await f.submit('text-after-image');
    await until(() => engine.turns.length === 2);
    assert.equal(engine.turns[1]!.image,null); assert.equal(f.coordinator.turns.get(next.turn_id).image_id,null);
    await f.coordinator.cancel(next.turn_id);
    await assert.rejects(f.coordinator.submit('invalid-image', { ...params,image_id: 'a'.repeat(64) }));
    assert.equal(engine.turns.length,2); assert.equal(f.coordinator.busy,false);
  } finally { await f.clean(); }
});
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
  active = true;
  const one = approvals.request(state,'write','one','check',100,signal,() => active);
  const two = approvals.request(state,'write','two','check',100,signal,() => active);
  const copies = approvals.list(); assert.notEqual(copies[0]!.approval_id,copies[1]!.approval_id);
  copies[0]!.command = 'tampered'; copies[0]!.approval_id = 'tampered';
  assert.equal(approvals.list()[0]!.command,'one'); assert.notEqual(approvals.list()[0]!.approval_id,'tampered');
  approvals.deny(); assert.deepEqual(await Promise.all([one,two]),[false,false]);
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
    const completed = f.store.connection.prepare("SELECT event_json FROM service_event WHERE json_extract(event_json,'$.kind')='turn.completed'").all()
      .map(row => JSON.parse(String(row.event_json)) as { session_id: string; turn_id: string; task_id: string });
    assert.deepEqual(new Set(completed.map(event => event.session_id)), new Set(['one', 'two']));
    for (const event of completed) {
      const owner = event.turn_id === second.turn_id ? second : background;
      assert.equal(event.session_id, owner.session_id); assert.equal(event.task_id, owner.task_id);
      const reply = new ChatRepository(f.store).messages(owner.session_id).find(message => message.id === `${owner.turn_id}-reply`);
      assert.equal(reply!.content, owner.turn_id);
    }
  } finally { await f.clean(); }
});
test('concurrent submissions retain one lane owner and shutdown settles every queued task', async () => {
  for (const completed of [3, 20]) {
  const f = await fixture();
  try {
    const turns = await Promise.all(Array.from({ length: 20 }, (_, index) => f.submit(`queue-${index}`)));
    await until(() => f.engines[0]?.turns.length === 1);
    const engine = f.engines[0]!;
    for (let index = 0; index < completed; index++) {
      assert.equal(engine.turns.length, index + 1);
      assert.equal(engine.turns[index]!.turnId, turns[index]!.turn_id);
      engine.emit(engine.turns[index]!, 'text.final', { text: 'done' });
      engine.emit(engine.turns[index]!, 'turn.completed');
      await until(() => index === 19 ? !f.coordinator.busy : engine.turns.length === index + 2);
    }
    await Promise.all([f.coordinator.close(), f.coordinator.close()]);
    assert.equal(engine.turns.length, Math.min(20, completed + 1)); assert.equal(engine.closed, true); assert.equal(f.coordinator.busy, false);
    assert.deepEqual(turns.map(turn => f.coordinator.turns.get(turn.turn_id).status), Array.from({ length: 20 }, (_, index) => index < completed ? 'completed' : 'cancelled'));
    assert.equal(f.coordinator.ledger.summary().pet.exp, completed === 3 ? 15 : 50);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM turn_settlement').get()!.n, 20);
    const sequences = f.store.connection.prepare('SELECT sequence FROM service_event ORDER BY sequence').all().map(row => row.sequence);
    assert.equal(new Set(sequences).size, sequences.length);
  } finally { await f.clean(); }
  }
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
test('provider failure details never become a successful reply, persisted secret or experience reward', async () => {
  const f = await fixture();
  try {
    const state = await f.submit('provider-failure'); await until(() => f.engines[0]?.turns.length === 1);
    f.engines[0]!.emit(f.engines[0]!.turns[0]!,'turn.failed',{ error: 'Incorrect API key sk-synthetic-private-provider-key', detail: 'Bearer synthetic-token' });
    await until(() => !f.coordinator.busy);
    const stored = f.coordinator.turns.get(state.turn_id);
    assert.equal(stored.status,'failed'); assert.match(stored.error,/模型配置或服务连接/);
    assert.equal(stored.output_text,''); assert.equal(f.coordinator.ledger.summary().pet.exp,0);
    for (const table of ['service_turn','service_event','chat_message','task_result']) {
      assert.doesNotMatch(JSON.stringify(f.store.connection.prepare(`SELECT * FROM ${table}`).all()),/sk-synthetic|Bearer synthetic|Incorrect API/);
    }
  } finally { await f.clean(); }
});
