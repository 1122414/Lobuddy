import { useEffect, useState } from 'react';
import type { ChatMessage, RelationView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

export function RelationshipPanel() {
  const [items, setItems] = useState<RelationView[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<RelationView | null>(null);
  const [sources, setSources] = useState<ChatMessage[]>([]);
  const [content, setContent] = useState('');
  const [deleteHistory, setDeleteHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const refresh = async () => { const [values, policy] = await Promise.all([request('relationship.list', {}), request('relationship.policy', {})]); setItems(values); setEnabled(policy.enabled ?? true); };
  useEffect(() => { let alive = true; void Promise.all([request('relationship.list', {}), request('relationship.policy', {})]).then(([values, policy]) => { if (alive) { setItems(values); setEnabled(policy.enabled ?? true); } }).catch(reason => { if (alive) setError(errorText(reason)); }); return () => { alive = false; }; }, []);
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setError(''); try { await fn(); await refresh(); setSelected(null); setSources([]); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } };
  const choose = async (value: RelationView) => { setSelected(value); setContent(value.content); setDeleteHistory(false); setSources([]); try { setSources(await request('relationship.sources', { relation_id: value.id })); } catch (reason) { setError(errorText(reason)); } };
  return <section className="knowledge-card" aria-label="她记住的我"><h3>她记住的我</h3>
    <p>明确偏好会自然留下；推测先向你确认。你随时可以纠正或让她忘记。</p>
    <label><input type="checkbox" checked={enabled} disabled={busy} onChange={event => { const next = event.target.checked; setEnabled(next); void act(async () => { try { return await request('relationship.configure', { enabled: next }); } catch (reason) { setEnabled(!next); throw reason; } }); }} />允许从相处中学习</label>
    <button disabled={busy} onClick={() => void act(refresh)}>刷新相处记忆</button>
    {error && <p role="alert" className="error">{error}</p>}
    {(['preference', 'shared', 'inferred'] as const).map(kind => <div key={kind}><h4>{kind === 'shared' ? '共同经历' : kind === 'inferred' ? '待确认的理解' : '偏好与边界'}</h4>{items.filter(item => item.kind === kind && ['active', 'pending'].includes(item.status)).map(item => <button key={item.id} disabled={busy} onClick={() => void choose(item)}>{item.status === 'pending' ? '待确认 · ' : ''}{item.content || '敏感内容：点开查看来源后决定'}</button>)}</div>)}
    {!items.some(item => ['active', 'pending'].includes(item.status)) && <p>还没有相处记忆。聊过的原文和已经记住的事情是分开的。</p>}
    {selected && <div><h4>{selected.key}</h4><p>{selected.reason} · 第 {selected.revision} 版 · {selected.scope === 'global' ? '跨会话' : '仅来源会话'}</p>
      <label>修正相处记忆<textarea value={content} maxLength={1000} onChange={event => setContent(event.target.value)} /></label>
      <button disabled={busy || !content.trim()} onClick={() => void act(() => request('relationship.edit', { relation_id: selected.id, content }))}>保存修正</button>
      {selected.status === 'pending' && <><button disabled={busy} onClick={() => void act(() => request('relationship.resolve', { relation_id: selected.id, approved: true }))}>确认记住</button><button disabled={busy} onClick={() => void act(() => request('relationship.resolve', { relation_id: selected.id, approved: false }))}>不要记住</button></>}
      <details><summary>来源消息</summary>{sources.map(source => <p key={source.id}>{source.content}<small> · {new Date(source.created_at || '').toLocaleString()}</small></p>)}</details>
      <label><input type="checkbox" checked={deleteHistory} onChange={event => setDeleteHistory(event.target.checked)} />同时删除 Lobuddy 中的来源聊天</label>
      <button disabled={busy} onClick={() => void act(() => request('relationship.forget', { relation_id: selected.id, delete_history: deleteHistory }))}>忘记这件事</button>
    </div>}
  </section>;
}

export function RememberedNotice({ sessionId }: { sessionId: string }) {
  const [ids, setIds] = useState<string[]>([]);
  const [error, setError] = useState('');
  useEffect(() => { setIds([]); return window.lobuddy?.subscribe(event => { if (event.session_id === sessionId && event.kind === 'relationship.remembered' && Array.isArray(event.data.ids)) setIds(event.data.ids.filter((id): id is string => typeof id === 'string')); }); }, [sessionId]);
  return ids.length ? <p role="status">记住了 · <button onClick={() => void Promise.all(ids.map(id => request('relationship.forget', { relation_id: id }))).then(() => setIds([])).catch(reason => setError(errorText(reason)))}>撤销</button>{error}</p> : null;
}
