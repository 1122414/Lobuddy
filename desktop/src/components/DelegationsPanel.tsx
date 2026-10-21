import { useEffect, useRef, useState } from 'react';
import type { ProjectView, DelegationDetail, DelegationSpec, DelegationView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

const labels: Record<string, string> = { draft: '待你确认', ready: '可以执行', scheduled: '等待时间', running: '正在处理', waiting_user: '等待你', waiting_event: '等待事件', paused: '已暂停', completed: '已完成', cancelled: '已取消', failed: '执行失败', needs_review: '结果待核对' };
const criteria = { reminder: '通知按规则投递（不代表已读）', 'source-digest': '资料来源覆盖且引用可追溯', 'organize-files': '副本数量和内容校验通过，原文件保留' };
const localTime = (seconds: number, timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone) => {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(seconds * 1000)).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
};
const terminal = new Set(['completed', 'cancelled', 'failed']);

export function DelegationsPanel() {
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [projectId, setProjectId] = useState('');
  useEffect(() => { void request('project.list', {}).then(setProjects).catch(() => undefined); }, []);
  const [items, setItems] = useState<DelegationView[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<DelegationDetail | null>(null);
  const [goal, setGoal] = useState('');
  const [kind, setKind] = useState<NonNullable<DelegationSpec['kind']>>('reminder');
  const [sources, setSources] = useState('');
  const [sourceDirectory, setSourceDirectory] = useState('');
  const [outputDirectory, setOutputDirectory] = useState('');
  const [at, setAt] = useState('');
  const [waitKind, setWaitKind] = useState<'none' | 'time' | 'event'>('time');
  const [waitEvent, setWaitEvent] = useState<'app_returned' | 'focus_finished' | 'delegation_completed'>('focus_finished');
  const [subjectId, setSubjectId] = useState('');
  const [frequency, setFrequency] = useState<'once' | 'daily' | 'weekly'>('once');
  const [weekdays, setWeekdays] = useState<number[]>([0]);
  const [endAt, setEndAt] = useState('');
  const [expires, setExpires] = useState(localTime(Date.now() / 1000 + 31 * 86400));
  const [editing, setEditing] = useState<DelegationView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const pendingCreate = useRef({ body: '', id: crypto.randomUUID() });
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [reminderTimezone, setReminderTimezone] = useState(timezone);
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
    const resolveTime = async (local: string) => (await request('schedule.resolve', { local, timezone: reminderTimezone })).at;
    const first = waitKind === 'time' ? await resolveTime(at) : null;
    const end = waitKind === 'time' && frequency !== 'once' && endAt ? await resolveTime(endAt) : null;
    const spec: DelegationSpec = {
      goal, kind, criteria: [criteria[kind]],
      repeat: waitKind === 'time' ? { frequency, local_time: frequency === 'once' ? '' : at.slice(11, 16), weekdays: frequency === 'weekly' ? weekdays : [], end_at: end } : { frequency: 'once' },
      sources: kind === 'source-digest' ? sources.split('\n').map(value => value.trim()).filter(Boolean) : [],
      source_directory: kind === 'organize-files' ? sourceDirectory : '',
      output_directory: kind === 'organize-files' ? outputDirectory : '',
      session_id: editing?.spec.session_id || '', source_message_id: editing?.spec.source_message_id || '',
      project_id: editing ? editing.spec.project_id : projectId,
      wait: waitKind === 'time' ? { kind: 'time', at: first, timezone: reminderTimezone } : waitKind === 'event' ? { kind: 'event', event: waitEvent, subject_id: waitEvent === 'delegation_completed' ? subjectId : '', timezone: reminderTimezone } : { kind: 'none', timezone: reminderTimezone },
    };
    const body = JSON.stringify(spec);
    if (pendingCreate.current.body !== body) pendingCreate.current = { body, id: crypto.randomUUID() };
    const value = editing
      ? await request('delegation.edit', { delegation_id: editing.id, revision: editing.revision, spec })
      : await request('delegation.create', spec, pendingCreate.current.id);
    setDetail(null); setSelected(value.id); setEditing(null); setGoal(''); setReminderTimezone(timezone); setAt(''); setEndAt(''); pendingCreate.current = { body: '', id: crypto.randomUUID() };
  });
  const change = (method: 'delegation.pause' | 'delegation.resume' | 'delegation.cancel' | 'delegation.run') => {
    const value = detail?.delegation;
    if (value) void action(() => request(method, { delegation_id: value.id, revision: value.revision }));
  };
  const edit = (value: DelegationView) => {
    setEditing(value); setGoal(value.spec.goal); setKind(value.spec.kind || 'reminder');
    setWaitKind(value.spec.wait?.kind === 'user' ? 'time' : value.spec.wait?.kind || 'none');
    setWaitEvent(value.spec.wait?.event || 'focus_finished'); setSubjectId(value.spec.wait?.subject_id || '');
    setSources(value.spec.sources?.join('\n') || '');
    setSourceDirectory(value.spec.source_directory || ''); setOutputDirectory(value.spec.output_directory || '');
    const zone = value.spec.wait?.timezone || timezone; setReminderTimezone(zone);
    setAt(value.spec.wait?.at ? localTime(value.spec.wait.at, zone) : '');
    setFrequency(value.spec.repeat?.frequency || 'once'); setWeekdays(value.spec.repeat?.weekdays || []); setEndAt(value.spec.repeat?.end_at ? localTime(value.spec.repeat.end_at, zone) : '');
  };
  const value = detail?.delegation;
  return <section className="knowledge" aria-label="托付给她的事">
    <div className="knowledge-heading"><div><h2>托付给她的事</h2><p>跨会话保留。先确认目标与范围，再开始处理；暂停不会抹掉已有产物。</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    <form className="settings-card" onSubmit={event => { event.preventDefault(); void save(); }}>
      <h3>{editing ? '修改后需要重新确认' : '新建委托草稿'}</h3>
      <label>关联项目<select value={editing ? editing.spec.project_id : projectId} disabled={Boolean(editing)} onChange={event => setProjectId(event.target.value)}><option value="">不关联项目</option>{projects.filter(p => p.status === 'active').map(p => <option key={p.id} value={p.id}>{p.name} · {p.id.slice(0, 6)}</option>)}</select></label><label>想托付的事<input required maxLength={2000} value={goal} onChange={event => setGoal(event.target.value)} /></label>
      <label>处理方式<select value={kind} onChange={event => { setKind(event.target.value as NonNullable<DelegationSpec['kind']>); setWaitKind(event.target.value === 'reminder' ? 'time' : 'none'); }}><option value="reminder">提醒我</option><option value="source-digest">归纳资料</option><option value="organize-files">整理文件副本</option></select></label>
      <label>何时开始<select aria-label="何时开始" value={waitKind} onChange={event => setWaitKind(event.target.value as typeof waitKind)}>{kind !== 'reminder' && <option value="none">我手动开始</option>}<option value="time">在指定时间</option><option value="event">在约定事件之后</option></select></label>
      {waitKind === 'event' && <><label>等待哪个事件<select aria-label="等待哪个事件" value={waitEvent} onChange={event => setWaitEvent(event.target.value as typeof waitEvent)}><option value="focus_finished">这一轮专注自然结束</option><option value="app_returned">下次回到 Lobuddy 窗口</option><option value="delegation_completed">指定委托完成</option></select></label>{waitEvent === 'delegation_completed' && <label>等待的委托<select aria-label="等待的委托" required value={subjectId} onChange={event => setSubjectId(event.target.value)}><option value="">请选择</option>{items.filter(item => item.id !== editing?.id && !terminal.has(item.status || 'draft')).map(item => <option key={item.id} value={item.id}>{item.spec.goal}</option>)}</select></label>}<p>只响应确认之后的新事件，提醒仍受安静规则约束。文件写入到时等待你核对，不会自动重放。</p></>}
      {waitKind === 'time' && <label>提醒时间 · {reminderTimezone}<input type="datetime-local" required value={at} onChange={event => setAt(event.target.value)} /></label>}
      {waitKind === 'time' && <><label>重复方式<select value={frequency} onChange={event => setFrequency(event.target.value as typeof frequency)}><option value="once">只执行一次</option><option value="daily">每天</option><option value="weekly">每周指定日</option></select></label>{frequency === 'weekly' && <fieldset><legend>星期</legend>{['一','二','三','四','五','六','日'].map((day,index) => <label key={index}><input type="checkbox" checked={weekdays.includes(index)} onChange={event => setWeekdays(values => event.target.checked ? [...values,index] : values.filter(value => value !== index))} />周{day}</label>)}</fieldset>}{frequency !== 'once' && <label>重复结束时间（可选）<input type="datetime-local" value={endAt} onChange={event => setEndAt(event.target.value)} /></label>}<p>提醒逾期 24 小时内补一次，周期遗漏合并；夏令时缺失时刻跳过，重复时刻只取第一次。文件写入或逾期任务等待核对。</p></>}
      {kind === 'source-digest' && <label>本次授权的文件或链接，每行一个<textarea required value={sources} onChange={event => setSources(event.target.value)} /></label>}
      {kind === 'organize-files' && <><label>输入目录<input required value={sourceDirectory} onChange={event => setSourceDirectory(event.target.value)} /></label><label>副本输出目录<input required value={outputDirectory} onChange={event => setOutputDirectory(event.target.value)} /></label></>}
      <p>验收：{criteria[kind]}。文件访问仍受工作区限制，写入仍须逐次审批。</p>
      <button disabled={busy} className="primary" type="submit">保存草稿</button>
      {editing && <button type="button" onClick={() => { setEditing(null); setGoal(''); setReminderTimezone(timezone); setAt(''); setEndAt(''); }}>放弃修改</button>}
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
        {value.spec.wait?.kind === 'event' && <p>等待：{{app_returned:'下次回到 Lobuddy 窗口',focus_finished:'这一轮专注自然结束',delegation_completed:'指定委托完成'}[value.spec.wait.event as typeof waitEvent]}{value.spec.wait.subject_id && ` · ${items.find(item => item.id === value.spec.wait?.subject_id)?.spec.goal || value.spec.wait.subject_id}`}</p>}
        {value.expires_at && <p>授权截止：{new Date(value.expires_at * 1000).toLocaleString()}</p>}
        {value.status === 'draft' && value.spec.kind === 'reminder' && value.spec.wait?.kind === 'user' && <p>时间还没确定。请先点“修改目标或时间”，明确日期、时间和时区，再确认安排。</p>}{value.status === 'draft' && value.spec.wait?.kind !== 'user' && <><label>授权有效至 · {timezone}<input type="datetime-local" value={expires} onChange={event => setExpires(event.target.value)} /></label><button disabled={busy} onClick={() => void action(() => request('delegation.confirm', { delegation_id: value.id, revision: value.revision, expires_at: new Date(expires).getTime() / 1000 }))}>确认目标和范围</button></>}
        {value.status === 'ready' && <button disabled={busy} className="primary" onClick={() => change('delegation.run')}>执行一次</button>}
        {!terminal.has(value.status || 'draft') && <div className="actions">
          {!['draft', 'paused'].includes(value.status || 'draft') && <button disabled={busy} onClick={() => change('delegation.pause')}>暂停</button>}
          {value.status === 'paused' && !value.active_run_id && <button disabled={busy} onClick={() => change('delegation.resume')}>继续等待</button>}
          {value.status !== 'running' && !value.active_run_id && <button disabled={busy} onClick={() => edit(value)}>修改目标或时间</button>}
          <button disabled={busy} onClick={() => change('delegation.cancel')}>取消委托</button>
        </div>}
        {value.active_run_id && ['paused','needs_review'].includes(value.status || '') && <div><button disabled={busy} onClick={() => void action(() => request('delegation.recover', {delegation_id:value.id, revision:value.revision, action:'inspect'}))}>只核对结果</button>{value.spec.kind === 'source-digest' && <button disabled={busy} onClick={() => void action(() => request('delegation.recover', {delegation_id:value.id, revision:value.revision, action:'resume_readonly'}))}>校验来源后继续只读任务</button>}<p>未知写操作不会重放；输入变化或授权失效时，请重新安排。</p></div>}
        <h4>执行记录与结果</h4>{detail?.runs.map(run => <article key={run.id}><p>{run.status} · {run.verdict === 'verified' ? '已验证' : run.verdict === 'failed' ? '验证失败' : '结果未知'}</p><p>{run.reason}</p><small>工作流：{run.workflow_version} · 任务：{run.turn_id || '尚未关联'}</small></article>)}
        {detail?.outcomes?.map(outcome => <details key={outcome.turn_id}><summary>实际来源与产物：{outcome.reason}</summary><p>{outcome.criteria?.join('；')}</p><pre>{JSON.stringify(outcome.evidence, null, 2)}</pre></details>)}
        {!detail?.runs.length && <p className="quiet">尚未执行</p>}
      </> : <p className="quiet">选择一项查看范围、等待条件与执行证据。</p>}
    </div></div>
  </section>;
}
