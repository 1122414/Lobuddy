import { useEffect, useRef, useState } from 'react';
import type { DiscoveryView } from '@lobuddy/contracts';
import { errorText, request } from '../api';

const suggestions = ['moeru-ai/airi','Project-N-E-K-O/N.E.K.O','Comfy-Org/ComfyUI'];
const statusText = { reading: '正在读取',ready: '已更新',empty: '近七天暂无正式发布',unavailable: '读取未完成，稍后再试',interrupted: '读取已暂停' };
export function DiscoveryPanel() {
  const [view,setView] = useState<DiscoveryView>();
  const [interests,setInterests] = useState('');
  const [repositories,setRepositories] = useState('');
  const [enabled,setEnabled] = useState(false);
  const [revision,setRevision] = useState(0);
  const [busy,setBusy] = useState(false), [notice,setNotice] = useState('');
  const mutation = useRef(0), pending = useRef(false), updating = useRef(false);
  useEffect(() => { let active = true, reading = false, initialized = false;
    const poll = async () => {
      if (!active || reading || updating.current) return;
      reading = true; const generation = mutation.current;
      try {
        const value = await request('discovery.get',{});
        if (!active || generation !== mutation.current) return;
        setView(value);
        if (!initialized) {
          initialized = true; setEnabled(value.policy.enabled); setRevision(value.policy.revision);
          setInterests(value.policy.interests.join('\n')); setRepositories(value.policy.repositories.join('\n'));
        }
        if (pending.current && !value.reading) {
          pending.current = false; setNotice('已检查可更新的来源；近期读过的项目会保留间隔。');
        }
      } catch (error) { if (active && generation === mutation.current) setNotice(errorText(error)); }
      finally { reading = false; }
    };
    void poll(); const timer = setInterval(() => void poll(),2000);
    return () => { active = false; clearInterval(timer); };
  },[]);
  const lines = (text: string) => text.split('\n').map(value => value.trim()).filter(Boolean);
  const save = async () => {
    if (!view) return;
    if (revision !== view.policy.revision) { setNotice('兴趣来源已在其他窗口更新，请重新打开后再修改。'); return; }
    updating.current = true; mutation.current++; setBusy(true); pending.current = false;
    try {
      const next = await request('discovery.configure',{ revision,enabled,
        interests: lines(interests),repositories: lines(repositories) });
      setView(next); setRevision(next.policy.revision); setInterests(next.policy.interests.join('\n')); setRepositories(next.policy.repositories.join('\n'));
      setNotice(enabled ? '兴趣来源已保存，空闲时会查找新的正式发布。' : '已停止发现新内容，并清除缓存。');
    } catch (error) { setNotice(errorText(error)); } finally { updating.current = false; setBusy(false); }
  };
  const refresh = async () => {
    updating.current = true; mutation.current++; setBusy(true);
    try {
      const next = await request('discovery.refresh',{}); setView(next); pending.current = next.reading;
      setNotice(next.reading ? '正在检查公开发布，可离开此页面。' : '已检查可更新的来源；近期读过的项目会保留间隔。');
    } catch (error) { setNotice(errorText(error)); } finally { updating.current = false; setBusy(false); }
  };
  return <section className="discovery-panel" aria-label="兴趣新鲜事"><h3>找些值得一起聊的新东西</h3>
    <p className="quiet">从你指定的公开项目查看近七天的正式发布，保留原文和时间。暂存的资讯与相处记忆分开保存。</p>
    <p className="quiet">免打扰、专注、正在聊天，或关闭主动陪伴/后台学习时暂停自动查找。你仍可手动检查。</p>
    <label className="setting-field">允许查找这些项目的新发布<input type="checkbox" disabled={!view || busy} checked={enabled} onChange={event => setEnabled(event.target.checked)} /></label>
    <div className="preference-field"><label>兴趣（每行一个，最多六项）<textarea aria-label="资讯兴趣" disabled={!view || busy} maxLength={246} placeholder={'AI 陪伴\n开源项目\n创作工具'} value={interests} onChange={event => setInterests(event.target.value)} /></label></div>
    <div className="preference-field"><label>公开 GitHub 项目（每行一个，最多三个）<textarea aria-label="资讯项目" disabled={!view || busy} maxLength={483} placeholder="moeru-ai/airi" value={repositories} onChange={event => setRepositories(event.target.value)} /></label></div>
    <p className="quiet">可以从这些项目开始：</p>
    <div>{suggestions.map(repository => <button key={repository} disabled={!view || busy} onClick={() => {
      const existing = lines(repositories); if (existing.length < 3 && !existing.some(item => item.toLowerCase() === repository.toLowerCase())) setRepositories([...existing,repository].join('\n'));
    }}>{repository}</button>)}</div>
    <button disabled={!view || busy} onClick={() => void save()}>保存兴趣来源</button>{' '}
    <button disabled={!view?.policy.enabled || view.reading || busy} onClick={() => void refresh()}>检查新发布</button>
    {view && <p className="quiet">今天已尝试读取 {view.used}/{view.daily_limit} 次；失败后至少等两小时，成功后至少等十二小时。</p>}
    {view?.attempts.map(item => <p key={item.repository}>{item.repository}：{statusText[item.status]}</p>)}
    {view?.items.map(item => <article key={item.id}><h4>{item.repository} · {item.title}</h4>
      <p className="quiet">发布于 {new Date(item.published_at * 1000).toLocaleDateString()} · 读取于 {new Date(item.checked_at * 1000).toLocaleString()}</p>
      <p>{item.text.slice(0,280)}</p><button onClick={() => void window.lobuddy?.openExternal(item.url).catch(error => setNotice(errorText(error)))}>查看官方原文</button>
    </article>)}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
