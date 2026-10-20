import { useEffect, useState } from 'react';
import type { NotificationView } from '../../../shared/desktop-protocol';
import { request, errorText } from '../api';

const status: Record<string, string> = { pending: '待投递', leased: '准备显示', delivered: '已投递，未读', read: '已读', missed: '已错过', cancelled: '已撤销' };
export function NotificationsPanel() {
  const [items, setItems] = useState<NotificationView[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true, busy = false;
    const refresh = async () => { if (busy) return; busy = true; try { const values = await request('notification.list', {}); if (alive) setItems(values); } catch (failure) { if (alive) setError(errorText(failure)); } finally { busy = false; } };
    void refresh(); const timer = setInterval(() => void refresh(), 2000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  const read = async (notification_id: string) => {
    try { const value = await request('notification.read', { notification_id }); setItems(items => items.map(item => item.id === value.id ? value : item)); }
    catch (failure) { setError(errorText(failure)); }
  };
  return <section className="knowledge" aria-label="通知收件箱"><h2>想看时，再慢慢看</h2><p>提醒与任务结果会留在这里。安静时不弹气泡；应用退出或电脑睡眠期间不会执行。</p>
    {error && <p role="alert" className="error">{error}</p>}
    {!items.length && <p className="quiet">暂时没有通知。</p>}
    {items.map(item => <article key={item.id} className="settings-card"><span className="eyebrow">{{ reminder: '你设定的提醒', task_result: '任务结果', companionship: '陪伴邀请' }[item.reason]} · {status[item.status || 'pending']}</span><h3>{item.text}</h3>
      <p>计划：{new Date(item.planned_at * 1000).toLocaleString()} · 保存：{new Date(item.created_at * 1000).toLocaleString()}</p>
      {item.decision && <details><summary>Jev 提示判断 · {item.decision.mode === 'shadow' ? '仅观察' : '参与投递'}</summary>
        <p>{item.decision.reason}</p><p>建议：{{ notify: '立即提示', defer: '延后合并', quiet: '仅留收件箱' }[item.decision.action || 'defer']} · {item.decision.model || '未取得有效模型结果'}</p>
        {item.decision.action === 'defer' && <p>最早提示：{new Date(item.decision.not_before * 1000).toLocaleString()}（仍须满足安静规则）</p>}
        {item.decision.answers && Object.entries(item.decision.answers).map(([key, value]) => <p key={key}>{{ relevant: '关联委托', time_sensitive: '时效性', duplicate: '重复内容' }[key]}：{value.choice} · 置信度 {Math.round(value.confidence * 100)}%</p>)}
        <p>判断耗时：{item.decision.elapsed_ms}ms · 输入 token：{item.decision.input_tokens ?? '未知'}；仅观察不会改变投递。</p>
      </details>}
      {item.delivered_at && <p>实际投递：{new Date(item.delivered_at * 1000).toLocaleString()}</p>}
      {item.read_at && <p>已读：{new Date(item.read_at * 1000).toLocaleString()}</p>}
      {!['read', 'cancelled', 'missed'].includes(item.status || 'pending') && <button onClick={() => void read(item.id)}>我看到了</button>}
    </article>)}
  </section>;
}
