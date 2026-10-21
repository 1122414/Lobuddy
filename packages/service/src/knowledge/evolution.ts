import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { z } from 'zod';
import { TurnStateSchema, type WorkflowView, type WorkflowDefinition } from '@lobuddy/contracts';
import { contextDefinition, digestDefinition, sanitizeMemory } from '@lobuddy/domain';
import { WorkflowRepository } from '../storage/workflows.js';
import { OutcomeRepository } from '../storage/outcomes.js';
import { parseStoredJson } from '../storage/json.js';
import { evaluateWorkflow } from '../tasks/workflow-evaluation.js';
const ContextProposal = z.strictObject({ format: z.enum(['pretty','compact']),reason: z.string().min(1).max(500) });
const DigestProposal = z.strictObject({ strategy: z.enum(['read-each-source','reuse-unchanged-local']),evidence_refs: z.array(z.string()).min(2).max(6),reason: z.string().min(1).max(500) });
export class WorkflowProposalError extends Error {
  constructor(readonly code: 'model_unavailable' | 'invalid_json' | 'invalid_proposal' | 'unmatched_evidence') { super(code); }
}
function proposal<T>(raw: string,schema: z.ZodType<T>): T {
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { throw new WorkflowProposalError('invalid_json'); }
  const result = schema.safeParse(parsed); if (!result.success) throw new WorkflowProposalError('invalid_proposal'); return result.data;
}
export class WorkflowEvolution {
  private readonly evaluating = new Map<string,Promise<WorkflowView>>();
  constructor(readonly workflows: WorkflowRepository) {}
  evidence(ids: string[]) {
    if (ids.length !== 1) return null;
    const id = ids[0]!,store = this.workflows.store,outcome = new OutcomeRepository(store).get(id);
    if (outcome.verdict !== 'verified' || outcome.scenario !== 'digest' || !Object.keys(outcome.metrics).length) return null;
    if (store.connection.prepare('SELECT 1 FROM relationship_barrier WHERE source_id=?').get(id)) return null;
    const row = store.connection.prepare('SELECT state_json FROM service_turn WHERE turn_id=?').get(id);
    if (!row || TurnStateSchema.parse(parseStoredJson(String(row.state_json))).status !== 'completed') return null;
    const groups = new Map<string,string[]>();
    for (const item of outcome.evidence) {
      if (typeof item.canonical_source !== 'string' || typeof item.ref !== 'string' || /^https?:\/\//.test(item.canonical_source)) continue;
      const group = groups.get(item.canonical_source) ?? []; group.push(item.ref); groups.set(item.canonical_source,group);
    }
    const duplicates = [...groups.values()].filter(refs => refs.length > 1);
    if (!duplicates.length || (outcome.metrics.physical_reads ?? 0) <= groups.size) return null;
    return { turn_id: id,verified: true,duplicate_reference_groups: duplicates,physical_reads: outcome.metrics.physical_reads!,source_count: outcome.metrics.source_count!,
      trace_sha256: createHash('sha256').update(JSON.stringify(outcome)).digest('hex') };
  }
  propose(definition: WorkflowDefinition,reason: string,evidence: string[]) {
    if (sanitizeMemory(reason) !== reason.trim()) throw Error('修改理由不能包含秘密');
    return this.workflows.propose(definition,reason,evidence);
  }
  evaluate(id: string,signal: AbortSignal,current: () => boolean = () => true): Promise<WorkflowView> {
    const existing = this.evaluating.get(id); if (existing) return existing;
    const promise = this.compare(id,signal,current).finally(() => this.evaluating.delete(id)); this.evaluating.set(id,promise); return promise;
  }
  private async compare(id: string,signal: AbortSignal,current: () => boolean) {
    const value = this.workflows.get(id); if (value.status !== 'candidate') return value;
    const stable = this.workflows.get(value.parent_id),trace = value.definition.name === 'source-digest' ? this.evidence(value.evidence) : null;
    let result = value.definition.name === 'source-digest' && !trace ? { decision: 'rejected',reason: '缺少已验证且仍有效的任务轨迹',cases: 0 } :
      await evaluateWorkflow(stable.definition,value.definition,signal);
    signal.throwIfAborted();
    if (trace) result = { ...result,source_trace: trace };
    if (!current() || trace && !isDeepStrictEqual(trace,this.evidence(value.evidence))) result = { decision: 'rejected',reason: '评测期间来源或学习授权已失效',cases: 0 };
    this.workflows.evaluated(id,result); return this.workflows.get(id);
  }
  async generate(source: string,model: (prompt: string,max: 1024 | 2048) => Promise<string>,signal: AbortSignal,current: () => boolean) {
    if (!current()) return null;
    const outcome = new OutcomeRepository(this.workflows.store).get(source); if (outcome.verdict !== 'verified') return null;
    let definition: WorkflowDefinition,reason: string;
    const call = async (prompt: string,max: 1024 | 2048) => {
      try { return await model(prompt,max); } catch { signal.throwIfAborted(); throw new WorkflowProposalError('model_unavailable'); }
    };
    if (outcome.scenario === 'digest') {
      const trace = this.evidence([source]); if (!trace || isDeepStrictEqual(this.workflows.active('source-digest').definition,digestDefinition(true))) return null;
      const raw = await call('根据实际执行证据提出资料归纳方法候选。只返回 JSON：strategy 只能是 read-each-source 或 reuse-unchanged-local；evidence_refs 必须引用同一重复读取组中至少两个真实编号；reason 说明依据。仅允许同一任务复用未变更本地来源，不缓存链接、不删来源、不改语义或权限。证据不含路径和正文：\n' + JSON.stringify(trace),2048);
      signal.throwIfAborted(); const proposed = proposal(raw,DigestProposal);
      if (!current() || !isDeepStrictEqual(trace,this.evidence([source]))) return null;
      if (new Set(proposed.evidence_refs).size < 2 || !trace.duplicate_reference_groups.some(group => proposed.evidence_refs.every(ref => group.includes(ref)))) throw new WorkflowProposalError('unmatched_evidence');
      definition = digestDefinition(proposed.strategy === 'reuse-unchanged-local'); reason = `依据 ${source} 的 ${proposed.evidence_refs.join('、')}；${proposed.reason}`;
    } else {
      const stable = this.workflows.active('assistant-context'); if (stable.definition.nodes[0]!.format === 'compact') return null;
      const raw = await call('提出低风险上下文工作流候选，减少序列化开销且保留全部字段。仅返回 JSON {"format":"pretty或compact","reason":"简短理由"}。不改权限、节点、评测、安全规则。开发样例：{"records":[{"id":"demo","description":"简短偏好"}]}。当前版本：' + JSON.stringify(stable.definition),1024);
      signal.throwIfAborted(); const proposed = proposal(raw,ContextProposal); if (!current()) return null;
      definition = contextDefinition(proposed.format); reason = proposed.reason;
    }
    const candidate = this.propose(definition,reason,[source]); return this.evaluate(candidate.version_id,signal,current);
  }
  forget(sources: Set<string>): void {
    for (const row of this.workflows.store.connection.prepare('SELECT id FROM workflow_version').all()) {
      const value = this.workflows.get(String(row.id)); if (!value.evidence.some(id => sources.has(id))) continue;
      if (value.active && value.parent_id) this.workflows.rollback(value.version_id,'来源已遗忘');
      this.workflows.store.run("UPDATE workflow_version SET reason='来源已遗忘',evidence='[]',evaluation='{}',status='rejected' WHERE id=?",value.version_id);
    }
  }
}
