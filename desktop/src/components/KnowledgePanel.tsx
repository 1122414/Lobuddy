import { SkillVersions } from './SkillVersions';
import { TopicPanel } from './TopicPanel';
import { RelationshipPanel } from './RelationshipPanel';
import { useEffect, useState } from 'react';
import type { MemoryItem, MemoryType, SkillCandidate, SkillDetail, SkillRecord } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

const kinds: Record<MemoryType, string> = {
  user_profile: '关于你', system_profile: '关于我', project_memory: '项目',
  conversation_summary: '对话摘要', episodic_memory: '共同经历', procedural_memory: '做事习惯',
};
const sourceName = (source?: string) => ({ manual: '你亲自记录', app_event: '应用内共同经历', bootstrap: '初始设定', migration: '旧版导入', strong_signal: '对话中明确告知', ai_patch: '对话中确认', auto: '任务中积累', import: '导入' }[source || ''] || source || '未注明');
const statuses: Record<string, string> = { active: '已启用', disabled: '已停用', draft: '草稿', needs_review: '待确认', archived: '已归档', deprecated: '已失效' };
export type Page = 'chat' | 'tasks' | 'memory' | 'skills' | 'history' | 'progress' | 'settings' | 'focus' | 'appearance' | 'companionship';

export function KnowledgePanel({ page }: { page: 'memory' | 'skills' }) {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [candidates, setCandidates] = useState<SkillCandidate[]>([]);
  const [query, setQuery] = useState('');
  const [memory, setMemory] = useState<MemoryItem | null>(null);
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [candidate, setCandidate] = useState<SkillCandidate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [removing, setRemoving] = useState(false);
  const refresh = async () => {
    const [m, s, c] = await Promise.all([request('memory.list', {}), request('skill.list', {}), request('skill.candidates', {})]);
    setMemories(m); setSkills(s); setCandidates(c);
  };
  useEffect(() => { let alive = true;
    Promise.all([request('memory.list', {}), request('skill.list', {}), request('skill.candidates', {})]).then(([m, s, c]) => {
      if (alive) { setMemories(m); setSkills(s); setCandidates(c); }
    }).catch(error => { if (alive) setError(errorText(error)); });
    return () => { alive = false; };
  }, []);
  const action = async (work: () => Promise<unknown>, message = '已保存，后续对话会使用更新后的内容。') => {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await work(); await refresh(); setNotice(message); } catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  };
  const openMemory = (item: MemoryItem) => { setMemory(item); setRemoving(false); setNotice(''); };
  const filtered = (value: string) => value.toLowerCase().includes(query.toLowerCase());
  return <section className="knowledge" aria-label={page === 'memory' ? '记忆管理' : '技能管理'}>
    <div className="knowledge-heading"><div><h2>{page === 'memory' ? '慢慢了解彼此' : '越来越懂你的做事方式'}</h2><p>{page === 'memory' ? '你可以随时纠正或删除我记住的内容。' : '只有已启用的技能会参与对话，停用后仍可恢复。'}</p></div>
      <button className="primary" onClick={() => { setNotice(''); setRemoving(false); setCandidate(null);
        if (page === 'memory') setMemory({ id: '', memory_type: 'user_profile', title: '', content: '', source: 'manual' });
        else setSkill({ record: { id: '', name: '', path: '', description: '' }, content: '---\nname: my-skill\ndescription: 描述适用的任务\n---\n\n## When to use\nUse this skill when the user asks for ...\n\n## Steps\n1. 描述执行步骤。\n' });
      }}>{page === 'memory' ? '添加记忆' : '添加技能'}</button></div>
    {page === 'memory' && <><RelationshipPanel /><TopicPanel /></>}
    <label className="search-label">筛选<input type="search" placeholder={page === 'memory' ? '查找记忆内容' : '查找技能'} value={query} onChange={event => setQuery(event.target.value)} /></label>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="knowledge-grid"><div className="knowledge-list">
      {page === 'memory' ? memories.filter(item => filtered(item.title + item.content)).map(item => <button className={`knowledge-card ${memory?.id === item.id ? 'selected' : ''}`} key={item.id} onClick={() => openMemory(item)}><span className="eyebrow">{kinds[item.memory_type]} · {statuses[item.status || 'active']}</span><strong>{item.title || '一段记忆'}</strong><span>{item.content}</span><small>来源：{sourceName(item.source)} · {item.updated_at?.slice(0, 10)}</small></button>)
        : <>{skills.filter(item => filtered(item.name + item.description)).map(item => <button className={`knowledge-card ${skill?.record.id === item.id ? 'selected' : ''}`} key={item.id} onClick={() => void action(async () => { setSkill(await request('skill.get', { skill_id: item.id })); setCandidate(null); }, '')}><span className="eyebrow">{statuses[item.status || 'draft']} · v{item.version || 1}</span><strong>{item.name}</strong><span>{item.description}</span><small>来源：{sourceName(item.source)} · 成功 {item.success_count || 0} 次</small></button>)}
          {candidates.map(item => <button className="knowledge-card" key={item.id} onClick={() => { setCandidate(item); setSkill(null); }}><span className="eyebrow">待审核的候选技能</span><strong>{item.title}</strong><span>{item.rationale}</span></button>)}</>}
      {(page === 'memory' ? memories.length : skills.length + candidates.length) === 0 && <p className="quiet">还没有记录，从右上角添加第一条吧。</p>}
    </div><div className="knowledge-editor">
      {page === 'memory' && memory ? <form key={memory.id} onSubmit={event => { event.preventDefault(); void action(async () => setMemory(await request('memory.save', { memory_id: memory.id || null, memory_type: memory.memory_type, title: memory.title || '', content: memory.content }))); }}>
        <h3>{memory.id ? '这条记忆' : '一条新的记忆'}</h3>
        <label>分类<select aria-label="分类" value={memory.memory_type} onChange={event => setMemory({ ...memory, memory_type: event.target.value as MemoryType })}>{Object.entries(kinds).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label>标题<input maxLength={100} value={memory.title || ''} onChange={event => setMemory({ ...memory, title: event.target.value })} /></label>
        <label>记忆内容<textarea aria-label="记忆内容" required maxLength={2000} rows={7} value={memory.content} onChange={event => setMemory({ ...memory, content: event.target.value })} /></label>
        {memory.id && <details><summary>查看来源</summary><dl><dt>记录 ID</dt><dd>{memory.id}</dd><dt>来源</dt><dd>{sourceName(memory.source)}</dd><dt>会话 ID</dt><dd>{memory.source_session_id || '手动添加'}</dd><dt>消息 ID</dt><dd>{memory.source_message_id || '—'}</dd><dt>可信度</dt><dd>{Math.round((memory.confidence || 0) * 100)}%</dd></dl></details>}
        <div className="editor-actions"><button className="primary" disabled={busy} type="submit">保存记忆</button>{memory.id && <button type="button" disabled={busy} className="danger" onClick={() => setRemoving(true)}>删除记忆</button>}</div>
        {removing && <div className="inline-confirm" role="alert"><p>删除这条长期记忆？原始聊天记录仍会保留。</p><button type="button" disabled={busy} onClick={() => void action(async () => { await request('memory.delete', { memory_id: memory.id }); setMemory(null); setRemoving(false); }, '记忆已删除。')}>确认删除</button><button type="button" onClick={() => setRemoving(false)}>保留</button></div>}
      </form> : page === 'skills' && skill ? <form key={skill.record.id} onSubmit={event => { event.preventDefault(); void action(async () => { const record = await request('skill.save', { skill_id: skill.record.id || null, name: skill.record.name, description: skill.record.description, content: skill.content || '' }); setSkill({ record, content: skill.content }); }); }}>
        <h3>{skill.record.id ? '技能详情' : '新技能'}</h3>
        {skill.content_error && <p className="error">{skill.content_error}</p>}
        <label>技能名称<input required disabled={!!skill.record.id} pattern="[A-Za-z0-9][A-Za-z0-9_-]*" maxLength={80} value={skill.record.name} onChange={event => setSkill({ ...skill, record: { ...skill.record, name: event.target.value } })} /></label>
        <label>适用场景<input required maxLength={500} value={skill.record.description} onChange={event => setSkill({ ...skill, record: { ...skill.record, description: event.target.value } })} /></label>
        <label>技能正文<textarea aria-label="技能正文" required maxLength={64000} rows={12} value={skill.content || ''} onChange={event => setSkill({ ...skill, content: event.target.value })} /></label>
        <p className="quiet">保留顶部的 --- 信息区和 When to use 触发说明；不要放入密钥或危险命令。</p>
        <details><summary>查看来源</summary><dl><dt>记录 ID</dt><dd>{skill.record.id || '保存后生成'}</dd><dt>来源</dt><dd>{sourceName(skill.record.source || 'manual')}</dd><dt>会话 ID</dt><dd>{skill.record.source_session_id || '手动添加'}</dd></dl></details>
        <div className="editor-actions"><button className="primary" disabled={busy} type="submit">保存技能</button>{skill.record.id && <><button disabled={busy} type="button" onClick={() => void action(async () => { await request('skill.toggle', { skill_id: skill.record.id, enabled: skill.record.status !== 'active' }); setSkill(await request('skill.get', { skill_id: skill.record.id })); }, skill.record.status === 'active' ? '技能已停用。' : '技能已启用。')}>{skill.record.status === 'active' ? '停用技能' : '启用技能'}</button><button type="button" disabled={busy} onClick={() => void action(async () => { await request('skill.archive', { skill_id: skill.record.id }); setSkill(await request('skill.get', { skill_id: skill.record.id })); }, '技能已归档。')}>归档</button></>}</div>
      {skill.record.id && <SkillVersions id={skill.record.id} version={skill.record.version || 1} />}</form> : page === 'skills' && candidate ? <div><h3>审核候选技能</h3><p>{candidate.rationale}</p><p>证据类型：{candidate.source_kind} · 修订 {candidate.revision}</p><pre>{JSON.stringify(candidate.evidence, null, 2)}</pre><pre className="candidate-content">{candidate.proposed_content}</pre><p className="quiet">来源会话：{candidate.source_session_id || '—'}</p><div className="editor-actions"><button className="primary" disabled={busy} onClick={() => void action(async () => { await request('skill.candidate.resolve', { candidate_id: candidate.id, approved: true }); setCandidate(null); }, '技能已审核并启用。')}>审核并启用</button><button disabled={busy} onClick={() => void action(async () => { await request('skill.candidate.resolve', { candidate_id: candidate.id, approved: false }); setCandidate(null); }, '已拒绝候选技能。')}>拒绝候选</button></div></div>
        : <div className="editor-empty"><h3>选择一条{page === 'memory' ? '记忆' : '技能'}</h3><p>查看内容、来源，或做一点调整。</p></div>}
    </div></div>
  </section>;
}
