import { createHash, randomUUID } from 'node:crypto';
import { ProjectCreateSchema, ProjectViewSchema, SourceViewSchema, TurnStateSchema,
  type ProjectCreate, type ProjectView, type SourceView, type SourceShare } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';

// Pydantic's serializer retains the float field type, including integral timestamps.
export function sourceFingerprint(value: SourceShare): string {
  const n = value.expires_at;
  const float = n === null ? 'null' : n !== 0 && (Math.abs(n) >= 1e16 || Math.abs(n) <= 1e-6) ?
    n.toExponential() : Number.isInteger(n) ? `${n}.0` : String(n);
  const json = JSON.stringify(value).replace(/("expires_at":)[^,}]*/u, `$1${float}`);
  return createHash('sha256').update(json).digest('hex');
}
export class ProjectRepository {
  constructor(readonly store: Store, readonly clock = () => Date.now() / 1000) {
    store.run('INSERT OR IGNORE INTO project_schema VALUES(1)');
  }
  projects(): ProjectView[] {
    return this.store.connection.prepare('SELECT body FROM personal_project ORDER BY rowid DESC').all()
      .map(row => ProjectViewSchema.parse(parseStoredJson(String(row.body))));
  }
  project(id: string): ProjectView {
    const row = this.store.connection.prepare('SELECT body FROM personal_project WHERE id=?').get(id);
    if (!row) throw Error('项目不存在，请明确选择项目'); return ProjectViewSchema.parse(parseStoredJson(String(row.body)));
  }
  private replay(requestId: string, fingerprint: string): string | undefined {
    const row = this.store.connection.prepare('SELECT fingerprint,entity_id FROM project_request WHERE id=?').get(requestId);
    if (!row) return;
    if (row.fingerprint !== fingerprint) throw Error('重复请求内容不一致'); return String(row.entity_id);
  }
  create(requestId: string, input: ProjectCreate): ProjectView {
    const spec = ProjectCreateSchema.parse(input), fingerprint = createHash('sha256').update(JSON.stringify(spec)).digest('hex');
    return this.store.transaction(() => {
      const prior = this.replay(requestId, fingerprint); if (prior) return this.project(prior);
      const value = ProjectViewSchema.parse({ ...spec, id: randomUUID(), created_at: this.clock(), updated_at: this.clock() });
      this.store.run('INSERT INTO personal_project VALUES(?,?)', value.id, JSON.stringify(value));
      this.store.run('INSERT INTO project_request VALUES(?,?,?)', requestId, fingerprint, value.id); return value;
    });
  }
  saveProject(input: ProjectView, revision: number): ProjectView {
    return this.store.transaction(() => {
      if (this.project(input.id).revision !== revision) throw Error('项目已更新，请刷新');
      const value = ProjectViewSchema.parse({ ...input, revision: revision + 1, updated_at: this.clock() });
      this.store.run('UPDATE personal_project SET body=? WHERE id=?', JSON.stringify(value), value.id); return value;
    });
  }
  sources(): SourceView[] {
    return this.store.connection.prepare('SELECT body FROM project_source ORDER BY rowid DESC').all()
      .map(row => SourceViewSchema.parse(parseStoredJson(String(row.body))));
  }
  source(id: string): SourceView {
    const row = this.store.connection.prepare('SELECT body FROM project_source WHERE id=?').get(id);
    if (!row) throw Error('来源不存在'); return SourceViewSchema.parse(parseStoredJson(String(row.body)));
  }
  replaySource(requestId: string, fingerprint: string): SourceView | undefined {
    const id = this.replay(requestId, fingerprint); return id ? this.source(id) : undefined;
  }
  add(input: SourceView, requestId: string, fingerprint: string): SourceView {
    const value = SourceViewSchema.parse(input);
    return this.store.transaction(() => {
      const prior = this.replaySource(requestId, fingerprint); if (prior) return prior;
      this.store.run('INSERT INTO project_source VALUES(?,?)', value.id, JSON.stringify(value));
      this.store.run('INSERT INTO project_request VALUES(?,?,?)', requestId, fingerprint, value.id); return value;
    });
  }
  saveSource(input: SourceView, revision: number): SourceView {
    return this.store.transaction(() => {
      const old = this.source(input.id);
      if (old.revision !== revision || old.status === 'forgotten') throw Error('来源已更新或遗忘，请刷新');
      const value = SourceViewSchema.parse({ ...input, revision: revision + 1 });
      this.store.run('UPDATE project_source SET body=? WHERE id=?', JSON.stringify(value), value.id); return value;
    });
  }
  selection(sessionId: string): { project_id: string; revision: number } {
    const row = this.store.connection.prepare('SELECT project_id,revision FROM project_session WHERE session_id=?').get(sessionId);
    return { project_id: String(row?.project_id ?? ''), revision: Number(row?.revision ?? 0) };
  }
  bind(sessionId: string, projectId: string, revision: number): void {
    this.store.transaction(() => {
      if (!this.store.connection.prepare('SELECT 1 FROM chat_session WHERE id=?').get(sessionId)) throw Error('会话不存在');
      if (this.selection(sessionId).revision !== revision) throw Error('会话项目关联已变化，请刷新');
      this.store.run(`INSERT INTO project_session VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET
        project_id=excluded.project_id,revision=excluded.revision`, sessionId, projectId, revision + 1);
    });
  }
  resetEngines(sessions: string[]): void {
    this.store.transaction(() => { for (const id of sessions) this.store.run('DELETE FROM engine_session WHERE session_id=?', id); });
  }
  sourceTurns(sourceId: string): string[] {
    return this.store.connection.prepare('SELECT turn_id FROM project_context_use WHERE source_id=?').all(sourceId).map(row => String(row.turn_id));
  }
  sourceSessions(sourceId: string): string[] {
    return [...new Set(this.store.connection.prepare('SELECT state_json FROM service_turn JOIN project_context_use USING(turn_id) WHERE source_id=?')
      .all(sourceId).map(row => TurnStateSchema.parse(parseStoredJson(String(row.state_json))).session_id))];
  }
  projectSessions(projectId: string): string[] {
    const sessions = new Set(this.store.connection.prepare('SELECT session_id FROM project_session WHERE project_id=?').all(projectId).map(row => String(row.session_id)));
    for (const row of this.store.connection.prepare('SELECT state_json FROM service_turn').all()) {
      const state = TurnStateSchema.parse(parseStoredJson(String(row.state_json)));
      if (state.project_id === projectId) sessions.add(state.session_id);
    }
    return [...sessions];
  }
  clearDerived(sourceId: string): void {
    this.store.transaction(() => {
      this.store.run('DELETE FROM conversation_summary'); this.store.run('DELETE FROM learning_job WHERE source_id=?', sourceId);
    });
  }
}
