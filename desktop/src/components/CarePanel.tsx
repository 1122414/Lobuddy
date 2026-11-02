import { useEffect, useState } from 'react';
import type { ResultsByMethod, ParametersByMethod } from '../../../shared/desktop-protocol';
import { request, errorText } from '../api';

const labels = { preparing: '准备中',active: '惦记着',deferred: '过些时候再聊',paused: '暂时不再问',closed: '已经结束',invalid: '来源已失效' };
export function CarePanel({ onPresetApplied = () => {} }: { onPresetApplied?: () => void }) {
  const [view,setView] = useState<ResultsByMethod['care.get']>();
  const [error,setError] = useState(''),[busy,setBusy] = useState(false);
  useEffect(() => {
    let alive = true, pending = false;
    const refresh = async () => { if (pending) return; pending = true;
      try { const next = await request('care.get',{}); if (alive) setView(next); }
      catch (e) { if (alive) setError(errorText(e)); } finally { pending = false; }
    };
    void refresh(); const timer = setInterval(() => { void refresh(); },3000);
    return () => { alive = false; clearInterval(timer); };
  },[]);
  const act = async (input: ParametersByMethod['care.update']) => {
    setBusy(true); try { await request('care.update',input); setView(await request('care.get',{})); setError(''); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  return <section aria-label="惦记的近况"><h3>惦记着你的事</h3><p className="quiet">只根据你在这里说过的近况，合适时再关心。未回应最多隔两天再问一次。</p>
    {view && <><label className="setting-field">允许持续关心普通近况<input type="checkbox" checked={view.policy.enabled} disabled={busy} onChange={e => {
      setBusy(true); void request('care.configure',{ ...view.policy,enabled: e.target.checked }).then(() => request('care.get',{})).then(setView).catch(e => setError(errorText(e))).finally(() => setBusy(false));
    }} /></label><p className="quiet">主动时段 {view.policy.start_hour}:00–{view.policy.end_hour}:00（{view.policy.timezone}）</p>
      <button disabled={busy} onClick={() => { setBusy(true); void request('care.preset',{apply: true}).then(() => request('care.get',{})).then(setView).then(() => { onPresetApplied(); setError('已应用：每天最多5次、间隔1小时，后台预算40次调用/160000输入/20000输出。'); }).catch(e => setError(errorText(e))).finally(() => setBusy(false)); }}>应用有存在感预设</button>
      <p className="quiet">应用预设会修改主动频率及后台预算上限，实际模型费用可能增加。</p>
      {view.items.length === 0 && <p className="quiet">有明确近况时，会在这里留下可查看、可暂停的记录。</p>}
      {view.items.map(item => <article key={item.id}><h4>{item.title} · {labels[item.status]}</h4><details><summary>来源原话</summary><p>{item.fact}</p></details>
        <p className="quiet">下次考虑：{new Date(item.next_at * 1000).toLocaleString('zh-CN',{timeZone: view.policy.timezone})}</p>
        {(['defer','pause','resume','close'] as const).map(action => <button key={action} disabled={busy || item.status === 'preparing'} onClick={() => void act({ id: item.id,revision: item.revision,action })}>{({ defer: '至少两天后再聊',pause: '暂时别再问',resume: '恢复关心',close: '这件事结束了' })[action]}</button>)}
      </article>)}</>}
    {error && <p role="status">{error}</p>}
  </section>;
}
