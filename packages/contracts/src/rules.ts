import { Temporal } from '@js-temporal/polyfill';
import type { RefinementCtx } from 'zod';
import { trimUserText } from './values.js';

type Wait = { kind: string; at: number | null; timezone: string; event: string; subject_id: string };
type Repeat = { frequency: string; local_time: string; weekdays: number[]; end_at: number | null };
const reject = (context: RefinementCtx, message: string) => context.addIssue({ code: 'custom', message });

export function validateWait(value: Wait, context: RefinementCtx): void {
  try {
    if (/^[+-]/.test(value.timezone)) throw new Error('Numeric offset is not an IANA timezone');
    Temporal.Now.zonedDateTimeISO(value.timezone);
  } catch { reject(context, '时区无效'); }
  if ((value.kind === 'time') !== (value.at !== null)) reject(context, '时间等待必须有明确时间，其他等待不能带时间');
  if ((value.kind === 'event') !== Boolean(value.event)) reject(context, '事件等待必须指定事件');
  if ((value.event === 'delegation_completed') !== Boolean(value.subject_id)) reject(context, '委托完成事件必须指定委托');
}

export function validateRepeat(value: Repeat, context: RefinementCtx): void {
  if (value.weekdays.some(day => day < 0 || day > 6) || new Set(value.weekdays).size !== value.weekdays.length) reject(context, '星期必须是互不重复的 0–6');
  if ((value.frequency !== 'once') !== Boolean(value.local_time)) reject(context, '周期提醒必须指定当地时刻');
  if ((value.frequency === 'weekly') !== Boolean(value.weekdays.length)) reject(context, '每周提醒必须指定星期');
}

type Delegation = { goal: string; kind: string; criteria: string[]; sources: string[];
  source_directory: string; output_directory: string; wait: Wait; repeat: Repeat };
export function validateDelegation(value: Delegation, context: RefinementCtx): void {
  if ([...value.sources, ...value.criteria].some(text => !trimUserText(text) || [...text].length > 2000)) reject(context, '来源和验收条件不能空白或过长');
  if (value.repeat.frequency !== 'once' && value.wait.kind !== 'time') reject(context, '周期规则只适用于时间等待');
  if (value.repeat.end_at !== null && (value.wait.at === null || value.repeat.end_at < value.wait.at)) reject(context, '结束时间不得早于首次提醒');
  if (value.repeat.frequency !== 'once' && value.wait.at !== null) {
    try {
      const instant = Temporal.Instant.fromEpochMilliseconds(Math.trunc(value.wait.at * 1000));
      const local = instant.toZonedDateTimeISO(value.wait.timezone);
      const earlier = local.toPlainDateTime().toZonedDateTime(value.wait.timezone, { disambiguation: 'earlier' });
      const time = `${String(local.hour).padStart(2, '0')}:${String(local.minute).padStart(2, '0')}`;
      if (local.year < 1 || local.year > 9999 || time !== value.repeat.local_time || local.second !== 0 || local.offset !== earlier.offset) reject(context, '首次提醒须与重复规则的当地时刻一致（重复时刻取第一次）');
      if (value.repeat.frequency === 'weekly' && !value.repeat.weekdays.includes(local.dayOfWeek - 1)) reject(context, '首次提醒须在所选星期内');
    } catch { reject(context, '日期或时区无效'); }
  }
  const criteria: Record<string, string[]> = { 'source-digest': ['资料来源覆盖且引用可追溯'],
    'organize-files': ['副本数量和内容校验通过，原文件保留'], reminder: ['通知按规则投递（不代表已读）'] };
  if (JSON.stringify(value.criteria) !== JSON.stringify(criteria[value.kind])) reject(context, '当前委托仅支持该场景列出的可验证验收条件');
  if (value.kind === 'source-digest' ? !value.sources.length : value.sources.length > 0) reject(context, '资料来源与委托类型不匹配');
  if (value.kind === 'organize-files') {
    if (!trimUserText(value.source_directory) || !trimUserText(value.output_directory)) reject(context, '文件整理需要明确输入和输出目录');
  } else if (value.source_directory || value.output_directory) reject(context, '当前委托类型不能包含整理目录');
  if (value.kind === 'reminder' && value.wait.kind === 'none') reject(context, '提醒需要明确的等待条件');
}

export function validateSourceMove(value: { project_id: string; session_id: string }, context: RefinementCtx): void {
  if (Boolean(value.project_id) === Boolean(value.session_id)) reject(context, '选择唯一项目或会话归属');
}
export function validateSource(value: { project_id: string; session_id: string; kind: string;
  text: string; locator: string; category: string; expires_at: number | null }, context: RefinementCtx): void {
  validateSourceMove(value, context);
  if (value.kind === 'text' && (!trimUserText(value.text) || value.locator)) reject(context, '文本分享需要正文，不能携带文件地址');
  if (value.kind !== 'text' && (!value.locator || value.text)) reject(context, '文件或链接需要明确来源，不能代填正文');
  if (value.category === 'recent' && value.expires_at === null) reject(context, '近况必须指定有效期');
}

type Workflow = { nodes: { id: string; kind: string; after: string[]; source: string; when: string;
  arguments: Record<string, unknown>; tool: string | null }[]; permissions: string[] };
export function validateWorkflow(value: Workflow, context: RefinementCtx): void {
  const seen = new Set(['input']);
  for (const node of value.nodes) {
    if (seen.has(node.id) || node.after.some(dep => !seen.has(dep))) reject(context, '节点重复、环或未按拓扑顺序声明');
    const refs = [node.source, node.when, ...Object.values(node.arguments)
      .filter((item): item is string => typeof item === 'string' && item.startsWith('$')).map(item => item.slice(1))];
    for (const ref of refs) {
      if (ref && !seen.has(ref.split('.')[0]!)) reject(context, '引用必须来自输入或已完成节点');
      if (ref && ref.split('.').some(part => {
        const text = part.replaceAll('_', '');
        return !text.length || /[^\p{L}\p{N}]/u.test(text);
      })) reject(context, '仅允许结构化字段引用');
    }
    if (node.kind === 'tool' && (node.tool === null || !value.permissions.includes(node.tool))) reject(context, '工具超出工作流权限范围');
    if (node.kind !== 'tool' && node.tool !== null) reject(context, '非工具节点不得声明工具');
    seen.add(node.id);
  }
  if (value.nodes.at(-1)?.kind !== 'output') reject(context, '最后一个节点必须输出结果');
}
