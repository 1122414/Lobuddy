import { useEffect, useState } from 'react';
import type { JevStatus } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

export function JevSettings() {
  const [status, setStatus] = useState<JevStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true, fetching = false;
    const refresh = async () => {
      if (fetching) return;
      fetching = true;
      try { const value = await request('jev.status', {}); if (alive) setStatus(value); }
      catch (failure) { if (alive) setError(errorText(failure)); }
      finally { fetching = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  const configure = async (mode: JevStatus['mode']) => {
    setBusy(true); setError('');
    try {
      await request('settings.patch', { values: { jev_mode: mode } });
      setStatus(await request('jev.status', {}));
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  };
  return <section className="knowledge-card" aria-label="Jev 提示时机">
    <h3>什么时候告诉你</h3>
    <p>Jev 帮忙判断任务结果是否值得现在提示。开启后会把结果短摘录、对应委托目标和同一委托近期已投递的结果发送给 TypeSafe，不发送完整聊天或录音。</p>
    <p className="quiet">专注、免打扰和你的安静边界始终优先；明确设定的提醒不交给 Jev。判断失败或不确定时延后十分钟合并，结果一直留在收件箱。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {status && <>
      <label>Jev 模式 <select aria-label="Jev 模式" value={status.mode} disabled={busy} onChange={event => void configure(event.target.value as JevStatus['mode'])}>
        <option value="off">关闭</option><option value="shadow">仅观察，不改变提示</option><option value="active">参与提示时机判断</option>
      </select></label>
      <p>{status.configured ? `已配置 · ${status.model}` : '尚未加载凭据，请在服务凭据配置 TypeSafe Jev 并重启。'} · {status.running ? '正在判断' : '空闲'}</p>
      <p>今日 {status.calls_today}/{status.daily_calls} 次 · 请求正文 {status.request_bytes_today}/{status.daily_request_bytes} 字节（独立预算，非 token 计费值）。每条结果最多调用一次，失败不自动重试。</p>
      {status.recent?.[0] && <p>最近：{status.recent[0].reason}</p>}
    </>}
  </section>;
}
