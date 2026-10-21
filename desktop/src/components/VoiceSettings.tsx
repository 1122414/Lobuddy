import { useEffect, useState } from 'react';
import type { VoiceStatus } from '../../../shared/desktop-protocol';
import { errorText, request } from '../api';

export function VoiceSettings() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState('');
  const [silence, setSilence] = useState(700);
  const [model, setModel] = useState<'s2.1-pro' | 's2.1-pro-free'>('s2.1-pro-free');
  useEffect(() => { let alive = true, initialized = false; const refresh = async () => { try { const value = await request('voice.get', {}); if (alive) { setStatus(value); if (!initialized) { setSilence(value.silence_ms ?? 700); setModel(value.fish_model ?? 's2.1-pro-free'); initialized = true; } } } catch (error) { if (alive) setError(errorText(error)); } }; void refresh(); const timer = setInterval(() => void refresh(), 1000); return () => { alive = false; clearInterval(timer); }; }, []);
  const save = async () => { try { setStatus(await request('voice.configure', { silence_ms: silence, fish_model: model })); setError(''); } catch (error) { setError(errorText(error)); } };
  return <section className="knowledge-card voice-settings"><h3>连续语音陪伴</h3><p>甜甜的台湾女孩 · 固定音色。麦克风音频在本机处理，不保存录音；识别文字发给对话模型，回答文字交给 Fish 合成。</p><p>本地识别：multilingual small · CPU int8。首次下载约 500 MB；下载失败仍可文字聊天。</p><button disabled={!status || status.downloading || status.model_ready} onClick={() => void request('voice.download', {}).then(setStatus).catch(error => setError(errorText(error)))}>{status?.model_ready ? '本地模型已就绪' : status?.downloading ? '正在下载并校验…' : '下载本地语音模型'}</button><label className="setting-field"><span>停顿多久结束一句（毫秒）</span><input aria-label="语音停顿阈值" type="number" min="300" max="2000" value={silence} onChange={event => setSilence(Number(event.target.value))} /></label><label className="setting-field"><span>Fish API 档位</span><select aria-label="Fish API 档位" value={model} onChange={event => setModel(event.target.value as typeof model)}><option value="s2.1-pro-free">免费开发与体验</option><option value="s2.1-pro">付费 API</option></select></label><p className="quiet">免费档无延迟保证，请求可能用于模型改进。付费 API 额度独立于网页积分。不会自动切换档位或音色。</p><button disabled={!status || !!status.voice_id} onClick={() => void save()}>保存语音设置</button><button onClick={() => void window.lobuddy?.windowAction('chat')}>打开快速聊天开始语音</button>{(error || status?.error) && <p role="alert" className="error">{error || status?.error}</p>}</section>;
}
