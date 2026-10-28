import type { DatabaseSync } from 'node:sqlite';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { lstat } from 'node:fs/promises';
import * as contract from '@lobuddy/contracts';
import { Store, StorageError } from './database.js';
import { atomicPrivateWrite, readPrivate } from './files.js';
import { parseStoredJson } from './json.js';

const JSON_COLUMNS: Record<string, Record<string, { parse(value: unknown): unknown }>> = {
  service_turn: { request_json: contract.TurnSendSchema, state_json: contract.TurnStateSchema },
  service_event: { event_json: contract.ServiceEventSchema },
  delegation: { body: contract.DelegationViewSchema }, delegation_revision: { body: contract.DelegationViewSchema },
  delegation_run: { body: contract.DelegationRunSchema }, delegation_request: { result: contract.JsonValueSchema },
  delegation_checkpoint: { body: contract.JsonRecordSchema, sources: contract.JsonRecordSchema },
  dialogue_boundary: { body: contract.QuietBoundarySchema }, dialogue_state: { body: contract.DialogueStateSchema },
  dialogue_invitation: { body: contract.JsonRecordSchema }, jev_decision: { body: contract.JevDecisionSchema },
  notification: { body: contract.NotificationViewSchema }, personal_project: { body: contract.ProjectViewSchema },
  project_source: { body: contract.SourceViewSchema }, pet_state: { personality_json: contract.PetPersonalitySchema },
  workflow_version: { body: contract.WorkflowDefinitionSchema, evidence: contract.JsonStringListSchema, evaluation: contract.JsonRecordSchema },
  relationship: { source_ids: contract.JsonStringListSchema }, relationship_revision: { value: contract.RelationViewSchema },
  task_acceptance: { body: contract.OutcomeSchema }, task_effect: { body: contract.JsonValueSchema },
  learning_job: { result: contract.JsonRecordSchema }, skill_candidate: { metadata: contract.JsonRecordSchema },
  skill_candidate_revision: { body: contract.SkillCandidateSchema },
  hitl_approval_log: { affected_paths_json: contract.JsonStringListSchema, risk_tags_json: contract.JsonStringListSchema },
  migration_record: { detail_json: contract.JsonRecordSchema }, turn_settlement: { progress_json: contract.JsonRecordSchema },
  user_themes: { colors_json: contract.JsonRecordSchema },
};
export function validateStoredJson(db: DatabaseSync): void {
  const tables = new Set(db.prepare("SELECT name FROM sqlite_schema WHERE type='table'").all().map(row => String(row.name)));
  if (tables.has('companion_handoff')) for (const row of db.prepare('SELECT * FROM companion_handoff').iterate()) {
    if (!contract.CompanionHandoffSchema.safeParse(row).success) throw new StorageError('资料记录校验失败：companion_handoff');
  }
  for (const [table, fields] of Object.entries(JSON_COLUMNS)) {
    if (!tables.has(table)) continue;
    for (const row of db.prepare(`SELECT * FROM "${table}"`).iterate()) {
      for (const [field, schema] of Object.entries(fields)) {
        if (row[field] === null || row[field] === undefined) continue;
        try { schema.parse(parseStoredJson(String(row[field]))); }
        catch { throw new StorageError(`资料记录校验失败：${table}.${field}；未覆盖原库`); }
      }
      if ('body' in fields && 'id' in row && typeof row.body === 'string') {
        const body: unknown = JSON.parse(row.body);
        if (body && typeof body === 'object' && !Array.isArray(body) && 'id' in body && body.id !== row.id) {
          throw new StorageError(`资料 ID 与正文不一致：${table}`);
        }
      }
    }
  }
}
const RECOVERY_REASON = '从旧版导入，需核对已有执行结果；未自动重放。';
export function recoverImportedWork(store: Store): void {
  const record = (kind: string, id: string) => store.run('INSERT OR IGNORE INTO ts_recovery(kind,entity_id,reason) VALUES(?,?,?)', kind, id, RECOVERY_REASON);
  for (const row of store.connection.prepare('SELECT turn_id,state_json FROM service_turn').all()) {
    const state = contract.TurnStateSchema.parse(JSON.parse(String(row.state_json)));
    if (['queued', 'running'].includes(state.status)) {
      state.status = 'interrupted'; state.error = RECOVERY_REASON;
      store.run('UPDATE service_turn SET state_json=? WHERE turn_id=?', JSON.stringify(state), String(row.turn_id));
      record('turn', state.turn_id);
    }
  }
  for (const row of store.connection.prepare('SELECT id,body FROM delegation').all()) {
    const state = contract.DelegationViewSchema.parse(JSON.parse(String(row.body)));
    // Keep authorization and immutable revisions as evidence; require an explicit recovery action.
    if (['scheduled', 'ready', 'running', 'waiting_user', 'waiting_event'].includes(state.status)) {
      state.status = 'needs_review'; state.reason = RECOVERY_REASON;
      store.run('UPDATE delegation SET body=? WHERE id=?', JSON.stringify(state), state.id); record('delegation', state.id);
    }
  }
  for (const row of store.connection.prepare('SELECT id,body FROM delegation_run').all()) {
    const state = contract.DelegationRunSchema.parse(JSON.parse(String(row.body)));
    if (['reserved', 'running'].includes(state.status)) {
      state.status = 'interrupted'; state.verdict = 'unknown'; state.reason = RECOVERY_REASON;
      store.run('UPDATE delegation_run SET body=? WHERE id=?', JSON.stringify(state), state.id); record('delegation-run', state.id);
    }
  }
  for (const row of store.connection.prepare("SELECT id FROM learning_job WHERE status='running'").all()) record('learning', String(row.id));
  store.run("UPDATE learning_job SET status='interrupted',error=? WHERE status='running'", RECOVERY_REASON);
  // Native DSH session files and old approvals remain evidence, not automatically resumable authority.
  for (const row of store.connection.prepare('SELECT engine_id FROM engine_session').all()) record('engine', String(row.engine_id));
}
function remap(path: string, oldRoot: string, newRoot: string): string {
  const absolute = isAbsolute(path) ? path : resolve(dirname(oldRoot), path);
  const suffix = relative(resolve(oldRoot), absolute);
  if (!suffix || suffix === '..' || suffix.startsWith(`..${sep}`) || isAbsolute(suffix)) throw new StorageError('资料资源超出已备份目录');
  return join(newRoot, suffix);
}
export async function relocateReferences(store: Store, manifest: contract.BackupManifest, stage: string, destination: string): Promise<void> {
  for (const row of store.connection.prepare('SELECT id,path,content FROM skill_record').all()) {
    const path = remap(String(row.path), manifest.source_workspace, join(destination, 'workspace'));
    const suffix = relative(join(destination, 'workspace'), path);
    if (!suffix.startsWith(`skills${sep}`)) throw new StorageError('旧技能路径不属于技能目录');
    let content = String(row.content);
    if (!content) content = (await readPrivate(join(stage, 'workspace', suffix), 256000)).toString('utf8');
    store.run('UPDATE skill_record SET path=?,content=? WHERE id=?', path, content, String(row.id));
  }
  for (const [table, field] of [['user_themes', 'source_image_path'], ['chat_message', 'image_path']] as const) {
    for (const row of store.connection.prepare(`SELECT id,"${field}" AS path FROM "${table}" WHERE "${field}" IS NOT NULL`).all()) {
      const path = String(row.path);
      if (!path || /^[a-f0-9]{64}$/.test(path)) continue;
      const replacement = remap(path, manifest.source_data, join(destination, 'data'));
      store.run(`UPDATE "${table}" SET "${field}"=? WHERE id=?`, replacement, String(row.id));
    }
  }
  const appearance = join(stage, 'data/pet_appearance.json');
  try { await lstat(appearance); } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return; throw error; }
  const value = contract.JsonRecordSchema.parse(JSON.parse((await readPrivate(appearance)).toString()));
  if (typeof value.custom_asset_path === 'string' && value.custom_asset_path) {
    value.custom_asset_path = remap(value.custom_asset_path, manifest.source_data, join(destination, 'data'));
    await atomicPrivateWrite(appearance, Buffer.from(JSON.stringify(value)));
  }
}
