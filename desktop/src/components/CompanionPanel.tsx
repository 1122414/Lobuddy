import { useEffect, useState } from 'react';
import type { ThemeView, CompanionPreferences } from '../../../shared/desktop-protocol';
import type { WindowStatus } from '../../../shared/desktop-api';
import { errorText, request } from '../api';
import { PetSprite, useCompanion } from '../companion';

export function CompanionPanel() {
  const [themes, setThemes] = useState<ThemeView[]>([]);
  const [themeName, setThemeName] = useState('我的主题');
  const [draft, setDraft] = useState<CompanionPreferences>({});
  const [status, setStatus] = useState<WindowStatus>();
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { let alive = true;
    void request('theme.list', {}).then(value => { if (alive) setThemes(value); }).catch(error => { if (alive) setNotice(errorText(error)); });
    void request('companion.get', {}).then(value => { if (alive) setDraft(value); }).catch(error => { if (alive) setNotice(errorText(error)); });
    void window.lobuddy?.windowStatus().then(value => { if (alive) setStatus(value); });
    return () => { alive = false; };
  }, []);
  const save = async () => { setBusy(true); try { setDraft(await request('companion.save', draft)); setNotice('外观已保存，桌宠会立即更新。'); } catch (error) { setNotice(errorText(error)); } finally { setBusy(false); } };
  return <section className="management-panel"><h2>让陪伴更像你喜欢的样子</h2><p className="quiet">沿用浊蒂的外形，性格从你们的相处中慢慢形成。</p><div className="appearance-preview"><PetSprite preferences={draft} activity="quiet" /></div>
    <label className="setting-field">宠物外观<select aria-label="宠物外观" value={draft.sprite || 'skadi-v2'} onChange={event => setDraft({ ...draft, sprite: event.target.value as CompanionPreferences['sprite'] })}><option value="skadi-v2">浊蒂 · 完整动画</option><option value="skadi">浊蒂 · 经典</option>{draft.image_id && <option value="custom">自定义图片</option>}</select></label>
    <button disabled={busy} onClick={() => { setBusy(true); void window.lobuddy?.pickPet().then(value => { if (value) { setDraft(value); setNotice('自定义外观已保存。'); } }).catch(error => setNotice(errorText(error))).finally(() => setBusy(false)); }}>选择自定义图片</button><p className="quiet">PNG、JPEG、GIF 或 WebP，最多 5 MB；动画保留原始帧。</p>
    <label className="setting-field">大小 · {Math.round((draft.scale ?? 1) * 100)}%<input type="range" min="0.5" max="2" step="0.05" value={draft.scale ?? 1} onChange={event => setDraft({ ...draft, scale: Number(event.target.value) })} /></label>
    <label className="setting-field">不透明度<input type="range" min="0.3" max="1" step="0.05" value={draft.opacity ?? 1} onChange={event => setDraft({ ...draft, opacity: Number(event.target.value) })} /></label>
    <label className="setting-field">桌宠保持在最前<input type="checkbox" checked={draft.always_on_top ?? true} onChange={event => setDraft({ ...draft, always_on_top: event.target.checked })} /></label>
    <label className="setting-field">主题强调色<input type="color" value={draft.accent || '#367572'} onChange={event => setDraft({ ...draft, accent: event.target.value })} /></label>
    <label className="setting-field">侧栏背景<input type="color" value={draft.side || '#deebec'} onChange={event => setDraft({ ...draft, side: event.target.value })} /></label>
    <div className="panel-actions"><button className="primary" disabled={busy} onClick={() => { void save(); }}>保存外观</button><button onClick={() => { void window.lobuddy?.windowAction('pet'); }}>显示桌宠</button><button onClick={() => { void window.lobuddy?.windowAction('chat'); }}>打开快速聊天</button></div>{notice && <p role="status">{notice}</p>}
    <h3>保存的主题</h3><p className="quiet">选择保存的配色，或从喜欢的图片提取新颜色。</p>
    <label className="setting-field">主题名称<input value={themeName} maxLength={80} onChange={event => setThemeName(event.target.value)} /></label>
    <div className="panel-actions"><button disabled={busy || !themeName.trim()} onClick={() => { setBusy(true); void request('theme.save', { name: themeName.trim(), accent: draft.accent || '#367572', side: draft.side || '#deebec' }).then(() => request('theme.list', {})).then(setThemes).catch(error => setNotice(errorText(error))).finally(() => setBusy(false)); }}>存为主题</button>
    <button disabled={busy} onClick={() => { setBusy(true); void window.lobuddy?.pickImage().then(async image => { if (image) { const colors = await request('theme.from_image', { image_id: image.image_id }); setDraft(value => ({ ...value, accent: colors.accent, side: colors.side })); setNotice('图片配色已生成，保存外观后生效。'); } }).catch(error => setNotice(errorText(error))).finally(() => setBusy(false)); }}>从图片提取配色</button>
    <button disabled={busy} onClick={() => setDraft(value => ({ ...value, accent: '#367572', side: '#deebec' }))}>恢复默认配色</button></div>
    {themes.map(theme => <div className="saved-theme" key={theme.theme_id}><span className="theme-swatch" style={{ background: theme.accent }} /><span>{theme.name}</span><button disabled={busy} onClick={() => { setBusy(true); void request('theme.apply', { theme_id: theme.theme_id }).then(() => request('companion.get', {})).then(setDraft).catch(error => setNotice(errorText(error))).finally(() => setBusy(false)); }}>应用</button><button disabled={busy} onClick={() => { setBusy(true); void request('theme.delete', { theme_id: theme.theme_id }).then(() => request('theme.list', {})).then(setThemes).catch(error => setNotice(errorText(error))).finally(() => setBusy(false)); }}>删除</button></div>)}
    <h3>快捷键</h3><dl className="shortcut-list">{Object.entries(status?.shortcuts || {}).map(([key, registered]) => <div key={key}><dt>{key.replace('CommandOrControl', '⌘ / Ctrl').replaceAll('+', ' + ')}</dt><dd>{key.endsWith('Space') ? '快速聊天' : key.endsWith('L') ? '管理窗口' : '开始 / 暂停专注'} · {registered ? '已启用' : '被占用，可使用托盘'}</dd></div>)}</dl>
  </section>;
}
export function FocusPanel() {
  const { focus } = useCompanion();
  const [minutes, setMinutes] = useState(25);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const action = async (method: 'focus.start' | 'focus.pause' | 'focus.resume' | 'focus.stop') => {
    setBusy(true); try { await request(method, method === 'focus.start' ? { minutes } : {}); setNotice(''); } catch (error) { setNotice(errorText(error)); } finally { setBusy(false); }
  };
  return <section className="management-panel focus-panel"><h2>这一会儿，陪你专心</h2><p className="quiet">计时期间安静陪伴，随时可以暂停。</p><div className="focus-clock" role="timer">{String(Math.floor(focus.seconds_remaining / 60)).padStart(2, '0')}:{String(focus.seconds_remaining % 60).padStart(2, '0')}</div><p>{{ focusing: '专注中', paused: '已暂停', break: '休息中', idle: '准备好了就开始' }[focus.state] || '本轮已结束'}</p>
    {!['focusing', 'paused', 'break'].includes(focus.state) && <label className="setting-field">专注时长（分钟）<input type="number" min="1" max="240" value={minutes} onChange={event => setMinutes(Number(event.target.value))} /></label>}
    <div className="panel-actions">{!['focusing', 'paused', 'break'].includes(focus.state) && <button className="primary" disabled={busy || !Number.isInteger(minutes) || minutes < 1 || minutes > 240} onClick={() => { void action('focus.start'); }}>开始专注</button>}{focus.state === 'focusing' && <button className="primary" disabled={busy} onClick={() => { void action('focus.pause'); }}>暂停专注</button>}{focus.state === 'paused' && <button className="primary" disabled={busy} onClick={() => { void action('focus.resume'); }}>继续专注</button>}{['focusing', 'paused', 'break'].includes(focus.state) && <button disabled={busy} onClick={() => { void action('focus.stop'); }}>结束专注</button>}</div>{notice && <p role="alert">{notice}</p>}
  </section>;
}
