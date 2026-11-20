import { randomUUID } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { CarePolicySchema, CareSourceClockSchema, TurnSendSchema, TurnStateSchema, ServiceEventSchema, localTimestamp, type TurnSend, type TurnState, type ServiceEvent } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
import { RpcFault } from '../fault.js';

export class TurnRepository {
  constructor(private readonly store: Store) {}
  submit(requestId: string, input: TurnSend, initialize?: (state: TurnState) => void): { state: TurnState; created: boolean } {
    const params = TurnSendSchema.parse(input);
    return this.store.transaction(() => {
      const found = this.store.connection.prepare('SELECT request_json,state_json FROM service_turn WHERE request_id=?').get(requestId);
      if (found) {
        if (!isDeepStrictEqual(TurnSendSchema.parse(parseStoredJson(String(found.request_json))), params)) throw new RpcFault('id_conflict');
        return { state: TurnStateSchema.parse(parseStoredJson(String(found.state_json))), created: false };
      }
      if (!this.store.connection.prepare('SELECT id FROM chat_session WHERE id=?').get(params.session_id)) throw new RpcFault('invalid_request');
      const mapped = this.store.connection.prepare('SELECT engine_id FROM engine_session WHERE session_id=? AND lane=?').get(params.session_id, params.lane);
      // Imported/crashed mappings are retained for audit but cannot drain historical input.
      const recovery = mapped && this.store.connection.prepare("SELECT 1 FROM ts_recovery WHERE kind='engine' AND entity_id=? AND acknowledged=0").get(mapped.engine_id!);
      const engineId = mapped && !recovery ? String(mapped.engine_id) : `lobuddy-${randomUUID().replaceAll('-', '')}`;
      if (!mapped || recovery) this.store.run(`INSERT INTO engine_session(session_id,lane,engine_id,ready) VALUES(?,?,?,0)
        ON CONFLICT(session_id,lane) DO UPDATE SET engine_id=excluded.engine_id,ready=0`, params.session_id, params.lane, engineId);
      const state = TurnStateSchema.parse({ turn_id: randomUUID(), task_id: randomUUID(), session_id: params.session_id,
        engine_id: engineId, lane: params.lane, status: 'queued', input_text: params.text, image_id: params.image_id, workflow_input: params.workflow_input,
        project_id: this.store.connection.prepare('SELECT project_id FROM project_session WHERE session_id=?').get(params.session_id)?.project_id ?? '' });
      initialize?.(state); TurnStateSchema.parse(state);
      this.store.run('INSERT INTO service_turn VALUES(?,?,?,?)', state.turn_id, requestId, JSON.stringify(params), JSON.stringify(state));
      const now = localTimestamp();
      const policy = this.store.connection.prepare("SELECT value FROM app_settings WHERE key='care_policy'").get();
      const timezone = policy ? CarePolicySchema.parse(parseStoredJson(String(policy.value))).timezone : Intl.DateTimeFormat().resolvedOptions().timeZone;
      // Keep the legacy display timestamp while retaining an absolute, source-bound scheduling clock.
      const clock = CareSourceClockSchema.parse({at: Date.now()/1000,timezone});
      this.store.run('INSERT INTO app_settings VALUES(?,?,?)',`care_clock:${state.turn_id}`,JSON.stringify(clock),now);
      this.store.run("INSERT INTO chat_message(id,session_id,role,content,created_at,image_path) VALUES(?,?,'user',?,?,?)",
        state.turn_id, state.session_id, params.text, now, params.image_id);
      this.store.run("UPDATE chat_session SET updated_at=?,title=CASE WHEN title='新对话' THEN ? ELSE title END WHERE id=?",
        now, [...params.text.trim()].slice(0, 30).join(''), params.session_id);
      return { state, created: true };
    });
  }
  engineReady(id: string): boolean {
    return Boolean(this.store.connection.prepare('SELECT ready FROM engine_session WHERE engine_id=?').get(id)?.ready);
  }
  refreshEngine(state: TurnState): void {
    const mapped = this.store.connection.prepare('SELECT engine_id FROM engine_session WHERE session_id=? AND lane=?').get(state.session_id,state.lane);
    if (mapped && !this.store.connection.prepare("SELECT 1 FROM ts_recovery WHERE kind='engine' AND entity_id=? AND acknowledged=0").get(mapped.engine_id!)) {
      state.engine_id = String(mapped.engine_id); return;
    }
    state.engine_id = `lobuddy-${randomUUID().replaceAll('-','')}`;
    this.store.transaction(() => {
      this.store.run(`INSERT INTO engine_session(session_id,lane,engine_id,ready) VALUES(?,?,?,0)
        ON CONFLICT(session_id,lane) DO UPDATE SET engine_id=excluded.engine_id,ready=0`, state.session_id,state.lane,state.engine_id);
      this.save(state);
    });
  }
  markEngineReady(id: string): void { this.store.run('UPDATE engine_session SET ready=1 WHERE engine_id=?', id); }
  blockEngine(id: string): void {
    this.store.run("INSERT OR IGNORE INTO ts_recovery(kind,entity_id,reason) VALUES('engine',?,'引擎断连，禁止自动重放')", id);
  }
  get(id: string): TurnState {
    const row = this.store.connection.prepare('SELECT state_json FROM service_turn WHERE turn_id=?').get(id);
    if (!row) throw new RpcFault('invalid_request');
    return TurnStateSchema.parse(parseStoredJson(String(row.state_json)));
  }
  list(): TurnState[] {
    return this.store.connection.prepare('SELECT state_json FROM service_turn ORDER BY rowid DESC LIMIT 100').all()
      .map(row => TurnStateSchema.parse(parseStoredJson(String(row.state_json))));
  }
  save(input: TurnState): void {
    const state = TurnStateSchema.parse(input);
    this.store.run('UPDATE service_turn SET state_json=? WHERE turn_id=?', JSON.stringify(state), state.turn_id);
  }
  saveReply(state: TurnState): void {
    if (state.status !== 'completed') return;
    this.store.run("INSERT OR IGNORE INTO chat_message(id,session_id,role,content,created_at) VALUES(?,?,'assistant',?,?)",
      `${state.turn_id}-reply`, state.session_id, state.output_text, localTimestamp());
  }
  event(state: TurnState, kind: string, data: ServiceEvent['data']): ServiceEvent {
    const insertion = this.store.run("INSERT INTO service_event(event_json) VALUES ('{}')");
    const event = ServiceEventSchema.parse({ sequence: Number(insertion.lastInsertRowid), session_id: state.session_id,
      task_id: state.task_id, turn_id: state.turn_id, delegation_id: state.delegation_id, run_id: state.run_id, project_id: state.project_id, kind, data });
    this.store.run('UPDATE service_event SET event_json=? WHERE sequence=?', JSON.stringify(event), event.sequence);
    return event;
  }
  interruptUnfinished(): TurnState[] {
    return this.store.transaction(() => {
      const interrupted: TurnState[] = [];
      for (const row of this.store.connection.prepare('SELECT state_json FROM service_turn').all()) {
        const state = TurnStateSchema.parse(parseStoredJson(String(row.state_json)));
        if (!['queued', 'running'].includes(state.status)) continue;
        state.status = 'interrupted'; state.error = '上次服务中断，未自动重放，请确认已有结果后再继续。'; this.save(state);
        this.store.run("INSERT OR IGNORE INTO ts_recovery(kind,entity_id,reason) VALUES('engine',?,?)", state.engine_id, state.error);
        interrupted.push(state);
      }
      return interrupted;
    });
  }
}
