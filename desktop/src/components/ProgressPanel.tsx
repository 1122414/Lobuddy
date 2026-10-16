import { useEffect, useState } from 'react';
import type { ProgressOverview } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';
const traits: Record<string, string> = { friendliness: '亲和', curiosity: '好奇', diligence: '勤勉', creativity: '创造力', technical_skill: '技术熟练度' };
const abilities: Record<string, string> = { advanced_chat: '深入交流', multi_task: '多任务协作', code_assist: '代码助手', creative_mode: '创意伙伴', social_butterfly: '表达更丰富', evolution_stage2: '成长阶段', evolution_stage3: '成熟阶段' };
export function ProgressPanel() {
  const [data, setData] = useState<ProgressOverview | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { let alive = true;
    const refresh = () => { void request('progress.get', {}).then(value => { if (alive) setData(value); }).catch(error => { if (alive) setError(errorText(error)); }); };
    refresh(); const unsubscribe = window.lobuddy?.subscribe(event => { if (event.kind === 'progress.changed') refresh(); });
    return () => { alive = false; unsubscribe?.(); };
  }, []);
  return <section className="management-panel">{error && <p role="alert">{error}</p>}{data && <>
    <div className="panel-intro"><h2>一起积累的日常</h2><p>一起做事，也一起成长。相处中的倾向会慢慢变化。</p></div>
    <div className="progress-stats"><article><span>等级</span><strong>Lv. {data.pet.level}</strong><small>{data.pet.exp} EXP · 阶段 {data.pet.evolution_stage}</small></article><article><span>一起完成</span><strong>{data.completed_tasks}</strong><small>项任务</small></article><article><span>模型用量</span><strong>{(data.usage.input + data.usage.output).toLocaleString()}</strong><small>服务商报告的 token · {data.usage.calls} 次调用</small></article></div>
    <div className="knowledge-card"><h3>表达倾向</h3><p className="quiet">明确告诉我的偏好和边界始终优先。</p>{Object.entries(data.pet.personality || {}).filter(([key]) => key in traits).map(([key, value]) => <label className="trait-row" key={key}><span>{traits[key]}</span><meter min={0} max={100} value={Number(value)} /><span>{Number(value).toFixed(1)}</span></label>)}</div>
    <h3>成长记录</h3><div className="knowledge-grid">{data.abilities.map(ability => <article className="knowledge-card" key={ability.id}><h3>{abilities[ability.id] || ability.name}</h3><p>{ability.unlocked_at ? '已解锁' : '还在成长中'}</p><small>{[ability.min_level && `等级 ${ability.min_level}`, ability.min_stage && `阶段 ${ability.min_stage}`, ability.trait && `${traits[ability.trait] || ability.trait} ${ability.trait_value}`, ability.tasks_completed && `完成 ${ability.tasks_completed} 项任务`].filter(Boolean).join(' · ')}</small></article>)}</div>
    <details className="knowledge-card"><summary>用量明细</summary><p>输入 {data.usage.input.toLocaleString()} · 输出 {data.usage.output.toLocaleString()} · 输入中缓存 {data.usage.cached.toLocaleString()}</p><p className="quiet">仅累计服务商实际返回的用量，未返回的调用不作估算。</p></details>
  </>}</section>;
}
