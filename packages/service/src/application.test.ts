import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { requestSchemas, responseSchemas, type Method, type ResultsByMethod, type BridgeEvent } from '@lobuddy/contracts';
import { createApplicationService } from './application-service.js';
import type { Engine } from './engine/runtime.js';
import type { Handler } from './rpc-server.js';

class ConversationEngine implements Engine {
  connected = false; closed = false; sequence = 0;
  readonly turns: Record<string, unknown>[] = [];
  readonly sessions: Record<string, unknown>[] = [];
  private pending: BridgeEvent[] = []; private wake?: () => void;
  async start() {}
  async call(method: string, params: Record<string, unknown>) {
    if (method === 'session.open') this.sessions.push(params);
    if (method === 'turn.send') {
      this.turns.push(params);
      this.emit(params,'text.final',{ text: '收到。' }); this.emit(params,'turn.completed');
    }
    if (method === 'analysis.run') throw Error('Idle model must not run during foreground tests');
    return {};
  }
  private emit(turn: Record<string, unknown>, kind: BridgeEvent['kind'], data: BridgeEvent['data'] = {}) {
    this.pending.push({ sessionId: String(turn.sessionId), taskId: String(turn.taskId), turnId: String(turn.turnId), sequence: ++this.sequence, kind, data }); this.wake?.();
  }
  async *events(ready?: () => void) {
    this.connected = true; ready?.();
    while (!this.closed) {
      if (this.pending.length) yield this.pending.shift()!;
      else await new Promise<void>(resolve => { this.wake = resolve; });
    }
  }
  async close() { this.closed = true; this.connected = false; this.wake?.(); }
}
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-app-ts-'));
  const options = { kind: 'connect', storage: { data: join(root,'data'),workspace: join(root,'workspace'),logs: join(root,'logs'),create: true } };
  let engine = new ConversationEngine();
  let service = await createApplicationService(options,() => {},() => engine);
  async function call<M extends Method>(method: M, input: unknown = {}, id = randomUUID()): Promise<ResultsByMethod[M]> {
    const handler = service.handlers[method] as Handler<M>;
    assert.ok(handler, `${method} must be implemented`);
    const params = requestSchemas[method].parse(input) as Parameters<Handler<M>>[0];
    const result = await handler(params,{ requestId: id, signal: new AbortController().signal });
    return responseSchemas[method].parse(result) as ResultsByMethod[M];
  }
  async function turn(session: string, text: string, id = randomUUID()) {
    const result = await call('turn.send',{ session_id: session,text },id);
    const start = Date.now();
    while (service.tasks.busy) { if (Date.now() - start > 4000) throw Error('turn did not settle'); await delay(5); }
    assert.equal(service.tasks.turns.get(result.turn_id).status,'completed');
    return result;
  }
  return { root, call, turn, engine: () => engine, service: () => service,
    restart: async () => { await service.close(); engine = new ConversationEngine(); options.storage.create = false; service = await createApplicationService(options,() => {},() => engine); },
    close: async () => { await service.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('application feeds explicit preferences into the first turn, corrects across sessions and forgets across restart', async () => {
  const f = await fixture();
  try {
    const one = await f.call('session.create',{ title: 'one' }), two = await f.call('session.create',{ title: 'two' });
    const first = await f.turn(one.id,'以后请叫我小禾');
    assert.match(String(f.engine().turns[0]!.context),/以后请叫我小禾/);
    await f.turn(two.id,'你好'); assert.match(String(f.engine().turns[1]!.context),/以后请叫我小禾/);
    await f.turn(one.id,'以后请叫我小满');
    assert.doesNotMatch(String(f.engine().turns[2]!.context),/小禾/);
    assert.notEqual(f.engine().sessions[0]!.sessionId,f.engine().sessions[2]!.sessionId,'Correction retires engine history before opening');
    const corrected = (await f.call('relationship.list')).find(item => item.status === 'active')!;
    assert.match(corrected.content,/小满/);
    await f.restart();
    assert.equal((await f.call('relationship.list')).find(item => item.id === corrected.id)!.status,'active','Superseded source barriers must not erase its replacement');
    await f.turn(two.id,'你好'); assert.match(String(f.engine().turns[0]!.context),/小满/);
    await f.call('relationship.forget',{ relation_id: corrected.id });
    await f.restart(); await f.turn(two.id,'你好');
    assert.doesNotMatch(String(f.engine().turns[0]!.context),/小禾|小满/);
    assert.equal((await f.call('history.search',{ query: '小禾',session_id: one.id,scope: 'all_sessions' })).results.length,0);
    assert.ok((await f.call('session.history',{ session_id: one.id })).some(message => message.id === first.turn_id),'Forgetting does not delete chat unless requested');
    const projection = await readFile(join(f.root,'workspace/USER.md'),'utf8'); assert.doesNotMatch(projection,/小禾|小满/);
  } finally { await f.close(); }
});
test('application settings, learning disable, dialogue boundaries and durable replay retain real state', async () => {
  const f = await fixture();
  try {
    const session = await f.call('session.create',{ title: 'learning off' });
    const policy = (await f.call('learning.get')).policy;
    await f.call('learning.configure',{ ...policy,enabled: false });
    const id = randomUUID(); await f.turn(session.id,'以后请叫我小禾',id); await f.turn(session.id,'以后请叫我小禾',id);
    assert.equal(f.engine().turns.length,1); assert.equal((await f.call('relationship.list')).length,0);
    assert.equal((await f.call('learning.get')).jobs.length,0);
    await f.turn(session.id,'先听我讲'); assert.match(String(f.engine().turns.at(-1)!.context),/listening/);
    await f.turn(session.id,'以后别提工作');
    const dialogue = await f.call('dialogue.get',{ session_id: session.id }); assert.equal(dialogue.boundaries[0]!.subject,'工作');
    await f.call('settings.patch',{ values: { user_name: '配置名字' } });
    await f.turn(session.id,'你好'); assert.match(String(f.engine().turns.at(-1)!.context),/配置名字/);
    await f.call('settings.patch',{ values: { user_name: '' } });
    assert.doesNotMatch(await readFile(join(f.root,'workspace/USER.md'),'utf8'),/配置名字/);
    await f.restart(); assert.equal((await f.call('learning.get')).state,'disabled');
    assert.equal((await f.call('dialogue.get',{ session_id: session.id })).boundaries[0]!.active,true);
  } finally { await f.close(); }
});
