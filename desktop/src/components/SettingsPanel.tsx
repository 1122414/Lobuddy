import { LearningSettings } from './LearningSettings';
import { useEffect, useState } from 'react';
import type { JsonValue, SettingsView } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';
const common: Record<string, string> = {
  user_name: '怎么称呼你', pet_name: '伙伴的名字', llm_model: '对话模型', llm_base_url: '模型服务地址',
  task_timeout: '任务超时（秒）', execution_local_tools_enabled: '查找与打开本地应用',
  execution_max_tool_calls_per_task: '每轮最多工具调用', execution_max_local_lookup_calls: '每轮最多本地查找',
  execution_max_tool_result_chars: '单次工具结果字数上限', hitl_approval_timeout_seconds: '审批等待时间（秒）',
  memory_session_search_enabled: '允许助手检索对话历史', memory_session_search_default_scope: '历史检索范围',
  memory_gateway_min_confidence: '记忆候选最低可信度', skill_auto_candidate_enabled: '从已完成任务提议技能',
  focus_default_minutes: '默认专注时长（分钟）', focus_break_minutes: '休息时长（分钟）',
  log_level: '日志级别',
};
const credentials = { llm_api_key: '模型服务', fish_api_key: 'Fish Audio 声音', llm_multimodal_api_key: '旧版图片模型' } as const;
function Field({ name, label, value, schema, change }: { name: string; label: string; value: JsonValue; schema: JsonValue; change: (value: JsonValue) => void }) {
  const descriptor = (schema && typeof schema === 'object' && !Array.isArray(schema) ? schema : {}) as Record<string, JsonValue>;
  const choices = descriptor.enum;
  return <label className="setting-field"><span>{label}</span>{typeof value === 'boolean' ? <input aria-label={label} type="checkbox" checked={value} onChange={event => change(event.target.checked)} /> : Array.isArray(choices) ? <select aria-label={label} value={String(value ?? '')} onChange={event => change(event.target.value)}>{choices.map(choice => <option key={String(choice)}>{String(choice)}</option>)}</select> : <input aria-label={label} name={name} type={typeof value === 'number' ? 'number' : 'text'} value={String(value ?? '')} step="any" onChange={event => change(typeof value === 'number' ? Number(event.target.value) : event.target.value)} />}</label>;
}
export function SettingsPanel() {
  const [data, setData] = useState<SettingsView | null>(null);
  const [patch, setPatch] = useState<Record<string, JsonValue>>({});
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('');
  const refresh = async () => setData(await request('settings.get', {}));
  useEffect(() => { let alive = true; void request('settings.get', {}).then(value => { if (alive) setData(value); }).catch(error => { if (alive) setError(errorText(error)); }); return () => { alive = false; }; }, []);
  const save = async () => { setBusy(true); setError(''); try { setData(await request('settings.patch', { values: patch })); setPatch({}); setNotice('设置已保存，重新启动后生效。'); } catch (error) { setError(errorText(error)); } finally { setBusy(false); } };
  const configure = async (account: keyof typeof credentials) => { setBusy(true); setError(''); try { if (!window.lobuddy) throw Error('请在桌面应用中使用'); const result = await window.lobuddy.configureCredential(account); await refresh(); setNotice(result.saved ? '已保存到钥匙串，重新启动后使用新凭据。' : '已取消输入。'); } catch (error) { setError(errorText(error)); } finally { setBusy(false); } };
  const field = (name: string) => data && <Field key={name} name={name} label={common[name] || name} value={patch[name] ?? data.values[name]} schema={data.schema_fields[name]} change={value => setPatch(previous => ({ ...previous, [name]: value }))} />;
  return <section className="management-panel"><div className="panel-intro"><h2>按你的习惯相处</h2><p>模型与执行设置在重新启动后生效。</p></div>{error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{data && <>
    <section className="knowledge-card"><h3>服务凭据</h3><p className="quiet">在系统密码输入框中填写，保存在 macOS 钥匙串。</p>{Object.entries(credentials).map(([key, label]) => <div className="credential-row" key={key}><span>{label}</span><span>{data.credentials[key] ? '已配置' : '未配置'}</span><button disabled={busy} onClick={() => void configure(key as keyof typeof credentials)}>设置{label}凭据</button></div>)}</section>
    <LearningSettings />
    <form onSubmit={event => { event.preventDefault(); void save(); }}><fieldset disabled={busy}><legend>常用设置</legend>{Object.keys(common).filter(key => key in data.values).map(field)}</fieldset><details className="knowledge-card"><summary>全部兼容设置</summary><p className="quiet">保留旧版配置。桌宠视觉项随新版宠物窗口启用；旧引擎专属配置仅用于兼容。</p><input aria-label="查找设置" placeholder="按配置名称筛选" value={filter} onChange={event => setFilter(event.target.value)} />{Object.keys(data.values).filter(key => !(key in common) && key.includes(filter)).map(field)}</details><div className="panel-actions"><button className="primary" disabled={busy || !Object.keys(patch).length}>保存设置</button>{data.restart_required && <button type="button" disabled={busy} onClick={() => void window.lobuddy?.restart()}>重新启动</button>}</div></form>
  </>}</section>;
}
