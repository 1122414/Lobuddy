import { WorkflowDefinitionSchema, WorkflowViewSchema, type WorkflowDefinition, JsonRecordSchema, JsonStringListSchema } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { contextDefinition } from '@lobuddy/domain';
export class WorkflowRepository {
  constructor(readonly store: Store) {
    this.seed(contextDefinition());
    for (const definition of [
      { name: 'organize-files',permissions: ['lobuddy_organize'],nodes: [
        { id: 'preview',kind: 'tool',tool: 'lobuddy_organize',arguments: { source: '$input.source',output: '$input.output' } },
        { id: 'copy',kind: 'tool',tool: 'lobuddy_organize',after: ['preview'],arguments: { source: '$input.source',output: '$input.output',preview_id: '$preview.preview_id' } },
        { id: 'check',kind: 'verify',after: ['copy'] },{ id: 'result',kind: 'output',source: 'check',after: ['check'] },
      ] },
      { name: 'source-digest',permissions: ['lobuddy_digest'],nodes: [
        { id: 'digest',kind: 'tool',tool: 'lobuddy_digest',arguments: { sources: '$input.sources' } },
        { id: 'result',kind: 'output',source: 'digest',after: ['digest'] },
      ] },
    ]) this.seed(WorkflowDefinitionSchema.parse(definition));
  }
  seed(input: WorkflowDefinition): void {
    const definition = WorkflowDefinitionSchema.parse(input), id = `builtin-${definition.name}-1`;
    this.store.transaction(() => {
      this.store.run("INSERT OR IGNORE INTO workflow_version(id,name,parent,body,reason,evidence,status) VALUES(?,?,?,?,'内置固定版本','[]','stable')",id,definition.name,'',JSON.stringify(definition));
      this.store.run('INSERT OR IGNORE INTO workflow_active(name,version_id) VALUES(?,?)',definition.name,id);
    });
  }
  get(id: string) {
    const row = this.store.connection.prepare('SELECT * FROM workflow_version WHERE id=?').get(id); if (!row) throw Error('工作流版本不存在');
    const active = Boolean(this.store.connection.prepare('SELECT 1 FROM workflow_active WHERE version_id=? AND enabled=1').get(id));
    const definition = WorkflowDefinitionSchema.parse(parseStoredJson(String(row.body)));
    const parent = this.store.connection.prepare('SELECT body FROM workflow_version WHERE id=?').get(String(row.parent));
    const before = parent ? JSON.stringify(WorkflowDefinitionSchema.parse(parseStoredJson(String(parent.body))),null,2).split('\n') : [];
    const after = JSON.stringify(definition,null,2).split('\n');
    const diff = ['--- stable','+++ candidate',`@@ -${before.length ? 1 : 0},${before.length} +1,${after.length} @@`,...before.map(line => '-' + line),...after.map(line => '+' + line)].join('\n');
    return WorkflowViewSchema.parse({ version_id: id,parent_id: row.parent,definition,
      reason: row.reason,evidence: JsonStringListSchema.parse(parseStoredJson(String(row.evidence))),status: row.status,
      evaluation: JsonRecordSchema.parse(parseStoredJson(String(row.evaluation))),observed: row.observed,active,diff });
  }
  active(name: string) {
    const row = this.store.connection.prepare('SELECT version_id FROM workflow_active WHERE name=? AND enabled=1').get(name);
    if (!row) throw Error('工作流已停用或不存在'); return this.get(String(row.version_id));
  }
  versions() { return this.store.connection.prepare('SELECT id FROM workflow_version ORDER BY rowid DESC LIMIT 100').all().map(row => this.get(String(row.id))); }
  propose(input: WorkflowDefinition,reason: string,evidence: string[]) {
    const definition = WorkflowDefinitionSchema.parse(input),stable = this.active(definition.name),body = JSON.stringify(definition);
    const id = createHash('sha256').update(stable.version_id + body + JSON.stringify(evidence)).digest('hex');
    this.store.run("INSERT OR IGNORE INTO workflow_version(id,name,parent,body,reason,evidence,status) VALUES(?,?,?,?,?,?,'candidate')",id,definition.name,stable.version_id,body,reason,JSON.stringify(evidence));
    return this.get(id);
  }
  evaluated(id: string,input: Record<string,unknown>): void {
    let result = JsonRecordSchema.parse(input);
    this.store.transaction(() => {
      const value = this.get(id); if (value.status !== 'candidate') return;
      let status = result.decision === 'rejected' ? 'rejected' : 'review';
      if (result.decision === 'promote') {
        const activated = this.store.run('UPDATE workflow_active SET version_id=? WHERE name=? AND version_id=? AND enabled=1',id,value.definition.name,value.parent_id).changes;
        if (activated === 1) status = 'probation';
        else {
          result = { ...result,decision: 'rejected',reason: '父版本已变化或停用；请基于当前启用版本重新提议',comparison_decision: 'promote' };
          status = 'rejected';
        }
      }
      this.store.run("UPDATE workflow_version SET evaluation=?,status=? WHERE id=? AND status='candidate'",JSON.stringify(result),status,id);
    });
  }
  enable(id: string): void {
    const value = this.get(id);
    this.store.transaction(() => {
      if (['stable','probation'].includes(value.status) && this.store.run('UPDATE workflow_active SET enabled=1 WHERE version_id=?',id).changes) return;
      if (!['review','stable'].includes(value.status) || value.evaluation.decision !== 'promote') throw Error('没有固定验证通过的晋升记录');
      if (this.store.run('UPDATE workflow_active SET version_id=?,enabled=1 WHERE name=? AND version_id=? AND enabled=1',id,value.definition.name,value.parent_id).changes !== 1) throw Error('稳定版本已变化，需要重新评测');
      this.store.run("UPDATE workflow_version SET status='probation' WHERE id=?",id);
    });
  }
  disable(id: string): void { this.store.run('UPDATE workflow_active SET enabled=0 WHERE version_id=?',id); }
  rollback(id: string,reason = '用户否定此次改变'): void {
    const value = this.get(id); if (!value.parent_id) throw Error('内置基线没有上一个版本，可停用');
    this.store.transaction(() => {
      // Changing the version must not revoke the user's decision to keep this workflow disabled.
      if (this.store.run('UPDATE workflow_active SET version_id=? WHERE version_id=?',value.parent_id,id).changes) {
        this.store.run("UPDATE workflow_version SET status='rolled_back',evaluation=? WHERE id=?",JSON.stringify({ ...value.evaluation,rollback_reason: reason }),id);
      }
    });
  }
  begin(id: string,runId: string): void { this.get(id); this.store.run("INSERT OR IGNORE INTO workflow_observation VALUES(?,?,'running')",runId,id); }
  observe(id: string,runId: string,good: boolean | null): void {
    const value = this.get(id);
    let changed = false;
    this.store.transaction(() => {
      const prior = this.store.connection.prepare('SELECT * FROM workflow_observation WHERE run_id=?').get(runId);
      if (prior && (prior.version_id !== id || prior.state !== 'running')) return;
      this.store.run('INSERT OR REPLACE INTO workflow_observation VALUES(?,?,?)',runId,id,good === null ? 'cancelled' : good ? 'passed' : 'failed'); changed = true;
      if (good && value.status === 'probation') this.store.run("UPDATE workflow_version SET observed=observed+1,status=CASE WHEN observed+1>=5 THEN 'stable' ELSE status END WHERE id=?",id);
    });
    if (changed && good === false && value.status === 'probation') this.rollback(id,'观察期出现回归或执行中断，已回退');
  }
  recover(): void {
    for (const row of this.store.connection.prepare("SELECT * FROM workflow_observation WHERE state='running'").all()) this.observe(String(row.version_id),String(row.run_id),false);
  }
  context(data: Record<string,unknown>,turnId: string): string {
    const clean = JsonRecordSchema.parse(data),runId = 'context:' + turnId;
    let value;
    try {
      const pinned = this.store.connection.prepare('SELECT version_id FROM workflow_observation WHERE run_id=?').get(runId);
      value = pinned ? this.get(String(pinned.version_id)) : this.active('assistant-context');
    } catch { return JSON.stringify(clean,null,2); }
    const good = isDeepStrictEqual(value.definition,contextDefinition(value.definition.nodes[0]!.format));
    this.observe(value.version_id,runId,good); return JSON.stringify(clean,null,good && value.definition.nodes[0]!.format === 'compact' ? undefined : 2);
  }
}
