import { useEffect, useState } from 'react';
import type { CompanionOverview, TopicView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

export function TopicPanel() {
  const [topics, setTopics] = useState<TopicView[]>([]);
  const [overview, setOverview] = useState<CompanionOverview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { let alive = true; void Promise.all([request('companionship.topics', {}), request('companionship.overview', {})]).then(([next, history]) => { if (alive) { setTopics(next); setOverview(history); } }).catch(reason => { if (alive) setError(errorText(reason)); }); return () => { alive = false; }; }, []);
  const unblock = async (id: string) => { setBusy(true); setError(''); try { await request('companionship.topic.unblock', { topic_id: id }); setTopics(await request('companionship.topics', {})); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } };
  return <section className="knowledge-card" aria-label="相处话题"><h3>共同经历与主动话题</h3>
    <p>气泡只依据应用里的记录；同一话题七天内不重复，新的相关记录除外。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {overview?.experiences.map(item => <article key={item.id}><p>{item.content}</p><small>{new Date(item.at).toLocaleString()} · {item.source === 'app_event' ? '应用事件' : '已保存记忆'}</small></article>)}
    {!overview?.experiences.length && <p>完成一次专注后，这里会留下真实记录。</p>}
    <h4>暂时不聊或不再提起</h4>{topics.filter(topic => topic.blocked || topic.cooldown_until > Date.now() / 1000).map(topic => <article key={topic.topic_id}><p>{topic.label}</p><span>{topic.blocked ? '不再主动提起' : '暂缓这个话题'}</span><button disabled={busy} onClick={() => void unblock(topic.topic_id)}>允许再次主动聊</button></article>)}
  </section>;
}
