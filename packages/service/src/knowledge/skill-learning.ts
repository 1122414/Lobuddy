import { SkillCandidateSchema, OutcomeSchema, type TurnState } from '@lobuddy/contracts';
import { stableIdentity, sanitizeMemory, SECRETS } from '@lobuddy/domain';
import { SkillManager } from './skill-manager.js';
import { OutcomeRepository } from '../storage/outcomes.js';
export function learnSkill(skills: SkillManager,state: TurnState): Record<string,string> {
  if (skills.store.connection.prepare('SELECT 1 FROM relationship_barrier WHERE source_id=?').get(state.turn_id)) return { skipped: 'forgotten_source' };
  let outcome = new OutcomeRepository(skills.store).get(state.turn_id);
  const correction = /^(?:以后|下次)(?:整理|归纳)/u.test(state.input_text) && sanitizeMemory(state.input_text) === state.input_text && !SECRETS.test(state.input_text);
  if (correction) outcome = OutcomeSchema.parse({ turn_id: state.turn_id,scenario: state.input_text.slice(0,4).includes('整理') ? 'organize' : 'digest',
    reason: '用户明确纠正下次做事方式，待审核',criteria: ['确认用户纠正及适用范围后验证'],evidence: [{ source_message_id: state.turn_id,quote: state.input_text }] });
  if (['cancelled','interrupted'].includes(state.status) || !['organize','digest'].includes(outcome.scenario)) return { skipped: 'no_result_evidence' };
  if (!['verified','failed'].includes(outcome.verdict) && !correction || !outcome.evidence.length) return { skipped: 'unknown_result' };
  const id = stableIdentity('result-skill:' + state.turn_id); if (skills.candidate(id)) return { candidate_id: id };
  const name = 'learned-' + outcome.scenario + '-' + id.slice(0,8);
  const steps = outcome.scenario === 'organize' ? '1. 确认指定输入与独立输出目录；用 lobuddy_organize 生成预览。\n2. 等待现有审批，用原 preview_id 创建分类副本。\n3. 检查数量和哈希；同名、源变更或路径异常时停止。' :
    '1. 确认用户提供的来源列表。\n2. 用 lobuddy_digest 读取有界来源。\n3. 保留来源编号，标注缺失；区分原文摘录与解释。';
  // Generated skills must satisfy the same static validator as manually saved skills.
  const content = `---\nname: ${name}\ndescription: 受控${outcome.scenario}任务的待审经验\n---\n## When to use\n仅用户明确派发同类任务且输入满足工具范围时；权限、预算和审批保持不变。\n# 步骤\n${steps}\n# 结果检查\n${outcome.criteria.join('\n')}\n# 失败反例\n模型宣称完成不能替代产物检查；缺失来源、同名副本、未知写入不得重试为成功。\n# 本次证据\n任务 ${state.task_id}；判定 ${outcome.verdict}。候选尚未证明在新任务上的效果。` +
    (correction ? '\n# 用户明确纠正（待审）\n' + state.input_text : '');
  skills.createCandidate(SkillCandidateSchema.parse({ id,title: `${outcome.scenario} · ${outcome.verdict} 经验`,rationale: outcome.reason,
    proposed_name: name,proposed_content: content,source_session_id: state.session_id,source_task_id: state.task_id,
    source_kind: correction ? 'correction' : outcome.verdict === 'verified' ? 'successful_task' : 'diagnosed_failure',confidence: 0.8,
    evidence: { turn_id: state.turn_id,verdict: outcome.verdict,criteria: outcome.criteria,evidence_count: outcome.evidence.length } }));
  return { candidate_id: id };
}
