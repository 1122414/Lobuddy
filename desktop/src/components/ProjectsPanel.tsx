import { useEffect, useRef, useState } from 'react';
import type { ProjectView, SourceShare, SourceView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

const labels = { material: '资料', recent: '明确近况', decision: '决定', pending: '未完事项', shared: '共同经历' };
const status = { active: '可使用', changed: '文件已变更', missing: '来源不可用', expired: '已到期', forgotten: '已遗忘' };

export function ProjectSelector({ sessionId }: { sessionId: string }) {
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [selected, setSelected] = useState('');
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    void Promise.all([request('project.list', {}), sessionId ? request('project.selection', { session_id: sessionId }) : Promise.resolve({ project_id: '', revision: 0 })]).then(([values, bound]) => { if (alive) { setProjects(values); setSelected(bound.project_id); setRevision(bound.revision); } }).catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [sessionId]);
  return <div className="project-selector"><label>本次关联项目<select aria-label="本次关联项目" disabled={!sessionId} value={selected} onChange={event => { const id = event.target.value; void request('project.bind', { session_id: sessionId, project_id: id, revision }).then(value => { setRevision(value.revision); setSelected(id); setError(''); }).catch(e => setError(errorText(e))); }}><option value="">不关联项目</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name} · {item.id.slice(0, 6)}{item.status !== 'active' ? '（暂停或结束）' : ''}</option>)}</select></label>{error && <p role="alert">{error}</p>}</div>;
}

export function ProjectsPanel({ sessionId }: { sessionId: string }) {
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [sources, setSources] = useState<SourceView[]>([]);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [kind, setKind] = useState<SourceShare['kind']>('text');
  const [category, setCategory] = useState<SourceShare['category']>('material');
  const [expires, setExpires] = useState('');
  const [sensitive, setSensitive] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState('');
  const [correction, setCorrection] = useState('');
  const [delegations, setDelegations] = useState<Array<{ id: string; status?: string; spec: { goal: string } }>>([]);
  const ids = useRef({ create: crypto.randomUUID(), share: crypto.randomUUID() });
  const refresh = async () => { const [p, s] = await Promise.all([request('project.list', {}), request('source.list', {})]); setProjects(p); setSources(s); };
  useEffect(() => { void refresh().catch(e => setError(errorText(e))); }, []);
  useEffect(() => { let alive = true; if (selected) void request('project.get', { project_id: selected }).then(v => { if (alive) setDelegations(v.delegations); }).catch(e => { if (alive) setError(errorText(e)); }); else setDelegations([]); return () => { alive = false; }; }, [selected, sources]);
  const perform = async (fn: () => Promise<unknown>) => { if (busy) return; setBusy(true); try { await fn(); await refresh(); setError(''); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } };
  const project = projects.find(p => p.id === selected);
  const share = async () => {
    const scope = selected ? { project_id: selected } : { session_id: sessionId };
    const options = { ...scope, title, category, sensitive_confirmed: sensitive, expires_at: expires ? new Date(expires).getTime() / 1000 : null };
    if (kind === 'file') await window.lobuddy?.pickSource(options);
    else await request('source.share', { ...options, kind, text: kind === 'text' ? text : '', locator: kind === 'url' ? text : '' }, ids.current.share);
    ids.current.share = crypto.randomUUID(); setText(''); setTitle(''); setSensitive(false);
  };
  return <section className="knowledge" aria-label="最近与我们"><h2>最近与我们</h2><p>只使用你明确分享的材料。项目相互独立；本次会话材料默认一天后不再使用，近况必须指定有效期。</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="settings-card"><h3>建立项目</h3><label>项目名称<input value={name} onChange={e => { setName(e.target.value); ids.current.create = crypto.randomUUID(); }} /></label><label>项目目标<textarea value={goal} onChange={e => { setGoal(e.target.value); ids.current.create = crypto.randomUUID(); }} /></label><button disabled={busy || !name.trim()} onClick={() => void perform(async () => { const item = await request('project.create', { name, goal }, ids.current.create); setSelected(item.id); setName(''); setGoal(''); ids.current.create = crypto.randomUUID(); })}>建立项目</button></div>
    <label>查看与分享范围<select aria-label="查看与分享范围" value={selected} onChange={e => { setSelected(e.target.value); ids.current.share = crypto.randomUUID(); }}><option value="">只用于当前会话</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name} · {item.id.slice(0, 6)}</option>)}</select></label>
    {project && <article className="settings-card"><h3>{project.name}</h3><p>{project.goal}</p><label>项目状态<select aria-label="项目状态" value={project.status || 'active'} onChange={e => { const value = e.target.value as 'active' | 'paused' | 'completed'; void perform(() => request('project.edit', { project_id: project.id, revision: project.revision || 1, name: project.name, goal: project.goal || '', status: value })); }}><option value="active">进行中</option><option value="paused">暂时放一放</option><option value="completed">已经结束</option></select></label>{delegations.map(d => <p key={d.id}>关联委托：{d.spec.goal} · {d.status}（可在“托付给她的事”查看授权和结果）</p>)}</article>}
    <div className="settings-card" onChange={() => { ids.current.share = crypto.randomUUID(); }}><h3>主动分享给她</h3><label>分享标题<input value={title} onChange={e => setTitle(e.target.value)} /></label><label>分享方式<select value={kind} onChange={e => setKind(e.target.value as SourceShare['kind'])}><option value="text">粘贴文字</option><option value="file">选择文本文件</option><option value="url">提交链接</option></select></label><label>内容用途<select value={category} onChange={e => setCategory(e.target.value as SourceShare['category'])}>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>{kind !== 'file' && <label>{kind === 'url' ? '来源链接' : '分享内容'}<textarea value={text} onChange={e => setText(e.target.value)} /></label>}<label>使用到什么时候<input aria-label="使用到什么时候" type="datetime-local" value={expires} onChange={e => setExpires(e.target.value)} /></label><label><input type="checkbox" checked={sensitive} onChange={e => setSensitive(e.target.checked)} />我明确同意将本项敏感内容用于所选范围（密钥仍不可保存）</label><button disabled={busy || !title.trim() || (!selected && !sessionId) || (category === 'recent' && !expires)} onClick={() => void perform(share)}>{kind === 'file' ? '选择文件并分享' : '确认分享'}</button></div>
    {sources.filter(s => selected ? s.project_id === selected : s.session_id === sessionId).map(item => <article className="settings-card" key={item.id}><span className="eyebrow">{labels[item.category]} · {status[item.status || 'active']}</span><h3>{item.title}</h3><p style={{ whiteSpace: 'pre-wrap' }}>{item.text}</p><small>来源：{item.locator || item.source_message_id || '用户主动分享'} · {item.id} · {new Date(item.created_at * 1000).toLocaleString()}</small><p>{item.reason}{item.expires_at ? ` · 有效至 ${new Date(item.expires_at * 1000).toLocaleString()}` : ''}</p>{item.status !== 'forgotten' && <><button disabled={busy} onClick={() => void perform(() => request('source.forget', { source_id: item.id, revision: item.revision || 1 }))}>遗忘这项来源</button>{item.kind === 'text' && <button onClick={() => { setEditing(item.id); setCorrection(item.text); }}>纠正内容</button>}<label>调整来源归属<select value={item.project_id || ''} onChange={e => { const project_id = e.target.value; void perform(() => request('source.move', { source_id: item.id, revision: item.revision || 1, project_id, session_id: project_id ? '' : sessionId })); }}><option value="">当前会话</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name} · {p.id.slice(0, 6)}</option>)}</select></label></>}{editing === item.id && <div><textarea aria-label="纠正后的内容" value={correction} onChange={e => setCorrection(e.target.value)} /><button disabled={busy} onClick={() => void perform(async () => { await request('source.correct', { source_id: item.id, revision: item.revision || 1, text: correction, sensitive_confirmed: sensitive }); setEditing(''); })}>保存纠正</button></div>}</article>)}
  </section>;
}
