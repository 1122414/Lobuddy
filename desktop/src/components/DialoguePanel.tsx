import { useEffect, useState } from 'react';
import type { DialogueState, QuietBoundary } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

export function DialoguePanel({ sessionId }: { sessionId: string }) {
  const [value, setValue] = useState<{ state: DialogueState | null; boundaries: QuietBoundary[] }>({ state: null, boundaries: [] });
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true, busy = false;
    setValue({ state: null, boundaries: [] }); setError('');
    const refresh = async () => {
      if (!sessionId || busy || !alive) return;
      busy = true;
      try {
        const next = await request('dialogue.get', { session_id: sessionId });
        if (alive) { setValue(next); setError(''); }
      } catch (failure) { if (alive) setError(errorText(failure)); }
      finally { busy = false; }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [sessionId]);
  return <div className="settings-card"><h3>现在怎样陪你</h3><p>{value.state ? { listening: '先听你讲，少问一些', discussing: '一起聊聊，不急着下结论', executing: '专心处理你交代的事', quiet: '尊重当前的话题边界' }[value.state.mode] : '自然接话，跟着你的节奏来。'}</p><p>这些交流状态有有效期，不会自动成为你的性格标签。每天的边界按 Asia/Shanghai 当日结束，提醒与任务不会因此被擅自改期。</p>{value.boundaries.filter(b => b.active).map(b => <article key={b.id}><p>暂不主动提起：{b.subject} · {b.expires_at ? new Date(b.expires_at * 1000).toLocaleString() : '直到你解除'}</p><button onClick={() => void request('dialogue.boundary.remove', { boundary_id: b.id }).then(() => setValue(v => ({ ...v, boundaries: v.boundaries.filter(item => item.id !== b.id) }))).catch(e => setError(errorText(e)))}>可以再聊这个了</button></article>)}{error && <p role="alert">{error}</p>}</div>;
}
