import { WorkflowDefinitionSchema, WorkflowViewSchema, type WorkflowDefinition, JsonRecordSchema, JsonStringListSchema } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
export class WorkflowRepository {
  constructor(readonly store: Store) {
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
    return WorkflowViewSchema.parse({ version_id: id,parent_id: row.parent,definition: WorkflowDefinitionSchema.parse(parseStoredJson(String(row.body))),
      reason: row.reason,evidence: JsonStringListSchema.parse(parseStoredJson(String(row.evidence))),status: row.status,
      evaluation: JsonRecordSchema.parse(parseStoredJson(String(row.evaluation))),observed: row.observed,active,diff: '' });
  }
  active(name: string) {
    const row = this.store.connection.prepare('SELECT version_id FROM workflow_active WHERE name=? AND enabled=1').get(name);
    if (!row) throw Error('工作流已停用或不存在'); return this.get(String(row.version_id));
  }
}
