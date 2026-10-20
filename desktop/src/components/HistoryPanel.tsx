import { useEffect, useState } from 'react';
import type { ConversationSummary, SessionSearchResponse } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';
export function HistoryPanel({ sessionId, onSelect }: { sessionId: string; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<'current_session' | 'all_sessions'>('current_session');
  const [result, setResult] = useState<SessionSearchResponse | null>(null);
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { let alive = true;
    if (sessionId) request('history.summaries', { session_id: sessionId }).then(value => { if (alive) setSummaries(value); }).catch(error => { if (alive) setError(errorText(error)); });
    return () => { alive = false; };
  }, [sessionId]);
  return <section className="knowledge" aria-label="历史检索"><div className="knowledge-heading"><div><h2>一起说过的话</h2><p>按关键词找回对话，或回顾当前会话的摘要。</p></div></div>
    <form className="history-search" onSubmit={event => { event.preventDefault(); setBusy(true); setError(''); request('history.search', { session_id: sessionId, query, scope }).then(setResult).catch(error => setError(errorText(error))).finally(() => setBusy(false)); }}>
      <label>关键词<input required maxLength={200} value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索聊过的内容" /></label><label>范围<select aria-label="范围" value={scope} onChange={event => setScope(event.target.value as typeof scope)}><option value="current_session">当前会话</option><option value="all_sessions">所有会话（遵循设置权限）</option></select></label><button disabled={!sessionId || busy} className="primary">搜索历史</button>
    </form>{error && <p className="error" role="alert">{error}</p>}
    {result && <div className="history-results"><p className="quiet">实际范围：{result.scope === 'all_sessions' ? '所有会话' : '当前会话'} · 找到 {result.total_shown} 条</p>{result.results?.map(item => <article className="history-result" key={item.message_id}><small>{item.role === 'user' ? '你' : 'Lobuddy'} · {item.created_at.slice(0, 16).replace('T', ' ')}</small><p>{item.content}</p><button onClick={() => onSelect(item.session_id)}>打开来源会话</button><small>消息 ID：{item.message_id}</small></article>)}</div>}
    <h3>当前会话摘要</h3>{summaries.length ? summaries.map(item => <details className="history-result" key={item.id}><summary>{item.created_at?.slice(0, 16).replace('T', ' ')} · {item.summary_type === 'rolling' ? '阶段摘要' : '会话摘要'}</summary><p className="summary-content">{item.content}</p><small>来源消息：{item.from_message_id} → {item.to_message_id}</small></details>) : <p className="quiet">对话积累到一定轮次后，会在这里留下摘要。</p>}
  </section>;
}
