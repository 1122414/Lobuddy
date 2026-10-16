import { useEffect, useState } from 'react';
import type { CompanionPolicy } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

const fields = { nickname: ['如何称呼你', '相处 · 称呼'], tone: ['你喜欢的表达方式', '相处 · 表达偏好'], boundary: ['你希望我尊重的边界', '相处 · 边界'], shared: ['想一起记住的经历', '相处 · 共同经历'] } as const;
type Preference = keyof typeof fields;
export function CompanionshipPanel() {
  const [policy, setPolicy] = useState<CompanionPolicy>({});
  const [preferences, setPreferences] = useState<Record<Preference, string>>({ nickname: '', tone: '', boundary: '', shared: '' });
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { let alive = true;
    void Promise.all([request('companionship.get', {}), request('memory.list', { query: '相处 ·' })]).then(([config, memories]) => {
      if (!alive) return; setPolicy(config); setLoaded(true);
      setPreferences(Object.fromEntries(Object.entries(fields).map(([key, [, title]]) => [key, memories.find(item => item.title === title)?.content || ''])) as Record<Preference, string>);
    }).catch(error => { if (alive) setNotice(errorText(error)); });
    return () => { alive = false; };
  }, []);
  const save = async () => { setBusy(true); try { setPolicy(await request('companionship.configure', policy)); setNotice('陪伴设置已保存。'); } catch (error) { setNotice(errorText(error)); } finally { setBusy(false); } };
  return <section className="management-panel"><h2>偶尔主动，也懂得安静</h2><p className="quiet">我只会根据在 Lobuddy 里的互动冒一个气泡，不会查看其他应用。没回应就安静一会儿。</p>
    <label className="setting-field">允许主动找你聊天<input disabled={!loaded || busy} type="checkbox" checked={policy.enabled ?? true} onChange={event => setPolicy({ ...policy, enabled: event.target.checked })} /></label>
    <label className="setting-field">免打扰<input disabled={!loaded || busy} type="checkbox" checked={policy.do_not_disturb ?? false} onChange={event => setPolicy({ ...policy, do_not_disturb: event.target.checked })} /></label>
    <label className="setting-field">每天最多几次<input disabled={!loaded || busy} type="number" min="0" max="10" value={policy.daily_limit ?? 3} onChange={event => setPolicy({ ...policy, daily_limit: Number(event.target.value) })} /></label>
    <label className="setting-field">最短间隔（分钟）<input disabled={!loaded || busy} type="number" min="1" max="1440" value={policy.interval_minutes ?? 60} onChange={event => setPolicy({ ...policy, interval_minutes: Number(event.target.value) })} /></label>
    <label className="setting-field">没回应后安静多久（分钟）<input disabled={!loaded || busy} type="number" min="1" max="10080" value={policy.ignore_minutes ?? 120} onChange={event => setPolicy({ ...policy, ignore_minutes: Number(event.target.value) })} /></label>
    <button className="primary" disabled={!loaded || busy} onClick={() => { void save(); }}>保存陪伴设置</button>
    <h3>你来告诉我，怎样相处更舒服</h3><p className="quiet">明确说出的偏好优先。清空后保存即可忘记；也可以在「记忆」中查看、修改和删除。</p>
    {(Object.entries(fields) as [Preference, readonly [string, string]][]).map(([key, [label]]) => <div className="preference-field" key={key}><label>{label}<textarea aria-label={label} disabled={!loaded || busy} maxLength={1000} value={preferences[key]} onChange={event => setPreferences({ ...preferences, [key]: event.target.value })} /></label><button disabled={!loaded || busy} onClick={() => { setBusy(true); void request('preference.save', { kind: key, content: preferences[key] }).then(() => setNotice(preferences[key].trim() ? '这条相处偏好已记住。' : '这条相处记录已忘记。')).catch(error => setNotice(errorText(error))).finally(() => setBusy(false)); }}>保存{label}</button></div>)}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
