import { createHash, randomUUID } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { JsonRecordSchema, OutcomeSchema, type RuntimeSettings, type TurnState } from '@lobuddy/contracts';
import { executeWorkflow, type WorkflowValues } from '@lobuddy/domain';
import { WorkflowRepository } from '../storage/workflows.js';
import { DelegationRepository } from '../storage/delegations.js';
import { OutcomeRepository } from '../storage/outcomes.js';
import { parseStoredJson } from '../storage/json.js';
import { GovernedTools } from '../tools/governed.js';

export class WorkflowExecution {
  constructor(readonly versions: WorkflowRepository,readonly delegations: DelegationRepository,readonly outcomes: OutcomeRepository) {}
  fingerprints(sources: string[], tools: GovernedTools): Record<string,string> | null {
    try {
      if (sources.some(source => /^https?:\/\//.test(source))) return null;
      return Object.fromEntries(sources.map(source => [source,createHash('sha256').update(tools.files.readBytes(source)).digest('hex')]));
    } catch { return null; }
  }
  prepare(state: TurnState, tools: GovernedTools): WorkflowValues | undefined {
    if (!state.run_id || this.delegations.get(state.delegation_id).spec.kind !== 'source-digest') return;
    const store = this.versions.store, sources = this.fingerprints(this.delegations.get(state.delegation_id).spec.sources,tools);
    const row = store.connection.prepare('SELECT * FROM delegation_checkpoint WHERE run_id=?').get(state.run_id);
    if (!sources) { if (row) throw Error('检查点来源已不可验证'); return; }
    if (row && (row.version !== state.workflow_version || !isDeepStrictEqual(parseStoredJson(String(row.sources)),sources))) throw Error('检查点来源或版本已改变');
    const values = row ? JsonRecordSchema.parse(parseStoredJson(String(row.body))) : { input: state.workflow_input };
    if (!row) store.run('INSERT INTO delegation_checkpoint VALUES(?,?,?,?)',state.run_id,state.workflow_version,JSON.stringify(sources),JSON.stringify(values));
    for (const item of Object.values(values)) if (item && typeof item === 'object' && !Array.isArray(item) && item.outcome) {
      const outcome = OutcomeSchema.parse(item.outcome); if (outcome.turn_id !== state.turn_id) throw Error('检查点证据不属于当前任务'); this.outcomes.save(outcome);
    }
    return values;
  }
  startBudget(runId: string,seconds: number): number {
    if (!runId) return seconds;
    const store = this.versions.store, now = this.delegations.clock();
    return store.transaction(() => {
      const row = store.connection.prepare('SELECT * FROM delegation_usage WHERE run_id=?').get(runId);
      const spent = row ? Number(row.spent) + (row.started_at === null ? 0 : Math.max(0,now - Number(row.started_at))) : 0;
      if (spent >= seconds) throw Error('原运行时间预算已耗尽');
      store.run('INSERT INTO delegation_usage VALUES(?,0,?,?) ON CONFLICT(run_id) DO UPDATE SET started_at=excluded.started_at,spent=excluded.spent',runId,now,spent);
      return seconds - spent;
    });
  }
  reserve(runId: string,limit: number): void {
    if (!runId) return; const store = this.versions.store;
    store.transaction(() => {
      const row = store.connection.prepare('SELECT calls FROM delegation_usage WHERE run_id=?').get(runId);
      if (!row || Number(row.calls) >= limit) throw Error('原运行调用预算已耗尽');
      store.run('UPDATE delegation_usage SET calls=calls+1 WHERE run_id=?',runId);
    });
  }
  finishBudget(runId: string): void {
    if (!runId) return; const store = this.versions.store;
    store.transaction(() => {
      const row = store.connection.prepare('SELECT * FROM delegation_usage WHERE run_id=?').get(runId);
      if (row && row.started_at !== null) store.run('UPDATE delegation_usage SET spent=?,started_at=NULL WHERE run_id=?',Number(row.spent) + Math.max(0,this.delegations.clock() - Number(row.started_at)),runId);
    });
  }
  async execute(state: TurnState, tools: GovernedTools, settings: RuntimeSettings, signal: AbortSignal,
    active: () => boolean, model: (prompt: string) => Promise<string>): Promise<string> {
    const version = this.versions.get(state.workflow_version); this.versions.active(version.definition.name);
    const spec = state.run_id ? this.delegations.get(state.delegation_id).spec : null;
    const limit = Math.min(settings.execution_max_tool_calls_per_task,spec?.max_tool_calls ?? Infinity);
    let calls = 0; const reserve = () => { if (++calls > limit) throw Error('工作流调用预算已耗尽'); this.reserve(state.run_id,limit); };
    const result = await executeWorkflow(version.definition,state.workflow_input,{
      signal,active,initial: this.prepare(state,tools),
      tool: async (name,args) => { reserve(); return tools.execute({ callId: randomUUID(),name,arguments: args }); },
      model: async prompt => { reserve(); return model(prompt); }, verify: () => JsonRecordSchema.parse(this.outcomes.get(state.turn_id)),
      checkpoint: values => {
        if (!state.run_id) return; const body = JSON.stringify(values);
        if (Buffer.byteLength(body) <= 256000) this.versions.store.run('UPDATE delegation_checkpoint SET body=? WHERE run_id=?',body,state.run_id);
      },
    });
    return typeof result === 'string' ? result : JSON.stringify(result,null,2);
  }
}
