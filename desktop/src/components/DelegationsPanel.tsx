import { useEffect, useRef, useState } from 'react';
import type { DelegationDetail, DelegationSpec, DelegationView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

const labels: Record<string, string> = { draft: '待你确认', ready: '可以执行', scheduled: '等待时间', running: '正在处理', waiting_user: '等待你', waiting_event: '等待事件', paused: '已暂停', completed: '已完成', cancelled: '已取消', failed: '执行失败', needs_review: '结果待核对' };
const criteria = { reminder: '通知按规则投递（不代表已读）', 'source-digest': '资料来源覆盖且引用可追溯', 'organize-files': '副本数量和内容校验通过，原文件保留' };
const localTime = (seconds: number) => { const date = new Date(seconds * 1000); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const terminal = new Set(['completed', 'cancelled', 'failed']);

export function DelegationsPanel() {
  const [items, setItems] = useState<DelegationView[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<DelegationDetail | null>(null);
  const [goal, setGoal] = useState('');
  const [kind, setKind] = useState<NonNullable<DelegationSpec['kind']>>('reminder');
  const [sources, setSources] = useState('');
  const [sourceDirectory, setSourceDirectory] = useState('');
  const [outputDirectory, setOutputDirectory] = useState('');
  const [at, setAt] = useState('');
  const [expires, setExpires] = useState(localTime(Date.now() / 1000 + 31 * 86400));
  const [editing, setEditing] = useState<DelegationView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const pendingCreate = useRef({ body: '', id: crypto.randomUUID() });
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const list = await request('delegation.list', {});
        const value = selected ? await request('delegation.get', { delegation_id: selected }) : null;
        if (alive) { setItems(list); setDetail(value); }
      } catch (failure) { if (alive) setError(errorText(failure)); }
    };
    void poll(); const timer = setInterval(() => void poll(), 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [selected, refresh]);
  const action = async (work: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await work(); setRefresh(value => value + 1); }
    catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  };
  const save = () => action(async () => {
    const spec: DelegationSpec = {
      goal, kind, criteria: [criteria[kind]],
      sources: kind === 'source-digest' ? sources.split('\n').map(value => value.trim()).filter(Boolean) : [],
      source_directory: kind === 'organize-files' ? sourceDirectory : '',
      output_directory: kind === 'organize-files' ? outputDirectory : '',
      session_id: editing?.spec.session_id || '', source_message_id: editing?.spec.source_message_id || '',
      project_id: editing?.spec.project_id || '',
      wait: kind === 'reminder' ? { kind: 'time', at: new Date(at).getTime() / 1000, timezone } : { kind: 'none', timezone },
    };
    const body = JSON.stringify(spec);
    if (pendingCreate.current.body !== body) pendingCreate.current = { body, id: crypto.randomUUID() };
    const value = editing
      ? await request('delegation.edit', { delegation_id: editing.id, revision: editing.revision, spec })
      : await request('delegation.create', spec, pendingCreate.current.id);
    setSelected(value.id); setEditing(null); setGoal(''); pendingCreate.current = { body: '', id: crypto.randomUUID() };
  });
  const change = (method: 'delegation.pause' | 'delegation.resume' | 'delegation.cancel' | 'delegation.run') => {
    const value = detail?.delegation;
    if (value) void action(() => request(method, { delegation_id: value.id, revision: value.revision }));
  };
  const edit = (value: DelegationView) => {
    setEditing(value); setGoal(value.spec.goal); setKind(value.spec.kind || 'reminder');
    setSources(value.spec.sources?.join('\n') || '');
    setSourceDirectory(value.spec.source_directory || ''); setOutputDirectory(value.spec.output_directory || '');
    setAt(value.spec.wait?.at ? localTime(value.spec.wait.at) : '');
  };
  const value = detail?.delegation;
  return <section className="knowledge" aria-label="托付给她的事">
    <div className="knowledge-heading"><div><h2>托付给她的事</h2><p>跨会话保留。先确认目标与范围，再开始处理；暂停不会抹掉已有产物。</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    <form className="settings-card" onSubmit={event => { event.preventDefault(); void save(); }}>
      <h3>{editing ? '修改后需要重新确认' : '新建委托草稿'}</h3>
      <label>想托付的事<input required maxLength={2000} value={goal} onChange={event => setGoal(event.target.value)} /></label>
      <label>处理方式<select value={kind} onChange={event => setKind(event.target.value as NonNullable<DelegationSpec['kind']>)}><option value="reminder">提醒我</option><option value="source-digest">归纳资料</option><option value="organize-files">整理文件副本</option></select></label>
      {kind === 'reminder' && <label>提醒时间 · {timezone}<input type="datetime-local" required value={at} onChange={event => setAt(event.target.value)} /></label>}
      {kind === 'source-digest' && <label>本次授权的文件或链接，每行一个<textarea required value={sources} onChange={event => setSources(event.target.value)} /></label>}
      {kind === 'organize-files' && <><label>输入目录<input required value={sourceDirectory} onChange={event => setSourceDirectory(event.target.value)} /></label><label>副本输出目录<input required value={outputDirectory} onChange={event => setOutputDirectory(event.target.value)} /></label></>}
      <p>验收：{criteria[kind]}。文件访问仍受工作区限制，写入仍须逐次审批。</p>
      <button disabled={busy} className="primary" type="submit">保存草稿</button>
      {editing && <button type="button" onClick={() => { setEditing(null); setGoal(''); }}>放弃修改</button>}
    </form>
    <div className="knowledge-grid"><div className="knowledge-list">
      {items.map(item => <button key={item.id} className={`knowledge-card ${selected === item.id ? 'selected' : ''}`} onClick={() => { setDetail(null); setSelected(item.id); }}><span>{labels[item.status || 'draft']}</span><strong>{item.spec.goal}</strong><small>{item.reason}</small></button>)}
      {!items.length && <p className="quiet">有想交代的事时，再慢慢加进来。</p>}
    </div><div className="settings-card">
      {value ? <><h3>{value.spec.goal}</h3><p>{labels[value.status || 'draft']} · 第 {value.revision} 版</p><p>{value.reason}</p>
        <p>来源：{value.spec.source_message_id || '你在委托面板明确填写'}</p>
        <p>范围：{value.spec.sources?.join('、') || [value.spec.source_directory, value.spec.output_directory].filter(Boolean).join(' → ') || '仅投递提醒'}</p>
        <p>验收：{value.spec.criteria.join('；')}</p>
        {value.spec.wait?.at && <p>计划时间：{new Date(value.spec.wait.at * 1000).toLocaleString('zh-CN', { timeZone: value.spec.wait.timezone })} · {value.spec.wait.timezone}</p>}
        {value.expires_at && <p>授权截止：{new Date(value.expires_at * 1000).toLocaleString()}</p>}
        {value.status === 'draft' && <><label>授权有效至 · {timezone}<input type="datetime-local" value={expires} onChange={event => setExpires(event.target.value)} /></label><button disabled={busy} onClick={() => void action(() => request('delegation.confirm', { delegation_id: value.id, revision: value.revision, expires_at: new Date(expires).getTime() / 1000 }))}>确认目标和范围</button></>}
        {value.status === 'ready' && <button disabled={busy} className="primary" onClick={() => change('delegation.run')}>执行一次</button>}
        {!terminal.has(value.status || 'draft') && <div className="actions">
          {!['draft', 'paused'].includes(value.status || 'draft') && <button disabled={busy} onClick={() => change('delegation.pause')}>暂停</button>}
          {value.status === 'paused' && !value.active_run_id && <button disabled={busy} onClick={() => change('delegation.resume')}>继续等待</button>}
          {value.status !== 'running' && !value.active_run_id && <button disabled={busy} onClick={() => edit(value)}>修改目标或时间</button>}
          <button disabled={busy} onClick={() => change('delegation.cancel')}>取消委托</button>
        </div>}
        <h4>执行记录与结果</h4>{detail?.runs.map(run => <article key={run.id}><p>{run.status} · {run.verdict === 'verified' ? '已验证' : run.verdict === 'failed' ? '验证失败' : '结果未知'}</p><p>{run.reason}</p><small>工作流：{run.workflow_version} · 任务：{run.turn_id || '尚未关联'}</small></article>)}
        {detail?.outcomes?.map(outcome => <details key={outcome.turn_id}><summary>实际来源与产物：{outcome.reason}</summary><p>{outcome.criteria?.join('；')}</p><pre>{JSON.stringify(outcome.evidence, null, 2)}</pre></details>)}
        {!detail?.runs.length && <p className="quiet">尚未执行</p>}
      </> : <p className="quiet">选择一项查看范围、等待条件与执行证据。</p>}
    </div></div>
  </section>;
}
