import { useEffect, useState } from 'react';
import type { LearningPolicy, LearningView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

const states = { disabled: '已关闭', idle: '等待学习事项', waiting: '等你空闲后处理', running: '正在处理', budget_exhausted: '今日预算已用完', closed: '服务已关闭' };
const jobs = { pending: '待处理', running: '处理中', completed: '已完成', failed: '失败', interrupted: '已中断' };
export function LearningSettings() {
  const [view, setView] = useState<LearningView | null>(null);
  const [draft, setDraft] = useState<LearningPolicy | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    const poll = async () => { try { const next = await request('learning.get', {}); if (alive) { setView(next); setError(''); } } catch (reason) { if (alive) setError(errorText(reason)); } };
    void poll(); const timer = setInterval(() => void poll(), 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  const policy = draft || view?.policy;
  const save = async () => {
    if (!policy) return;
    setBusy(true); setError('');
    try { setView(await request('learning.configure', policy)); setDraft(null); }
    catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };
  return <section className="knowledge-card" aria-label="后台学习">
    <h3>后台学习</h3><p>在你空闲时整理，聊天和语音优先。当前巡检只报告问题，不会自动删除记忆。</p>
    {error && <p role="alert" className="error">{error}</p>}
    {view && policy && <>
      <p role="status">{states[view.state]}</p>
      <form onSubmit={event => { event.preventDefault(); void save(); }}><fieldset disabled={busy}>
        <label className="setting-field">允许后台学习<input type="checkbox" checked={policy.enabled ?? true} onChange={event => setDraft({ ...policy, enabled: event.target.checked })} /></label>
        {(['idle_seconds', 'daily_calls', 'daily_input_tokens', 'daily_output_tokens'] as const).map((key, i) => <label className="setting-field" key={key}>{['空闲多久开始（秒）', '每日模型调用上限', '每日输入 token 上限', '每日输出 token 上限'][i]}<input type="number" min={key === 'idle_seconds' ? 1 : 0} required value={policy[key]} onChange={event => setDraft({ ...policy, [key]: Number(event.target.value) })} /></label>)}
        <button disabled={!draft || busy}>保存学习设置</button>
      </fieldset></form>
      <p>今日已预留：{view.usage.calls} 次调用 · 输入 {view.usage.input_tokens} · 输出 {view.usage.output_tokens} token。中断或用量未知的调用仍保留预留额度。</p>
      <details><summary>实际接线与近期运行</summary>
        {view.consumers.map(item => <p key={item.setting}><strong>{item.setting}</strong>：{item.enabled ? '启用' : '未启用'} · {item.behavior}</p>)}
        {!view.jobs.length && <p>还没有后台处理记录。</p>}
        {view.jobs.map(job => <div key={job.id}><p>{job.kind === 'maintenance' ? '记忆与技能巡检' : job.kind} · {jobs[job.status]} · 已尝试 {job.attempts} 次</p><p>{new Date(job.updated_at * 1000).toLocaleString()}{job.error && ` · ${job.error}`}</p>{job.status === 'completed' && <pre>{JSON.stringify(job.result, null, 2)}</pre>}</div>)}
      </details>
    </>}
  </section>;
}
