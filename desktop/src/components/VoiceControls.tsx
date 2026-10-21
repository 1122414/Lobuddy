import { useEffect, useRef, useState } from 'react';
import type { VoiceStatus } from '../../../shared/desktop-protocol';
import { errorText } from '../api';
import { VoiceController } from '../voice';
import { Icon } from './Icon';

export function VoiceControls({ session, create }: { session: string; create: () => Promise<string> }) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef<VoiceController | null>(null);
  const activeSession = useRef('');
  useEffect(() => {
    const voice = new VoiceController((status, error) => { setStatus(status); if (error) setError(error); });
    controller.current = voice;
    const off = window.lobuddy?.onVoiceStop(() => { void voice.stop(); });
    const stop = () => { void voice.stop(); };
    window.addEventListener('pagehide', stop);
    return () => { off?.(); window.removeEventListener('pagehide', stop); void voice.stop(); };
  }, []);
  useEffect(() => { if (activeSession.current && session !== activeSession.current) { void controller.current?.stop(); activeSession.current = ''; } }, [session]);
  const act = async (fn: () => Promise<void>) => { setBusy(true); setError(''); try { await fn(); } catch (error) { setError(errorText(error)); } finally { setBusy(false); } };
  const labels = { loading: '正在准备本地识别…', listening: '我在听，直接说就好', thinking: '想一想…', speaking: '正在说话，可以打断', muted: '麦克风已关闭', error: '语音暂不可用', off: '' };
  return <div className="voice-controls">{status?.voice_id ? <><span role="status">{labels[status.state || 'off']}</span><button disabled={busy} onClick={() => void act(() => controller.current!.mute(status.state !== 'muted'))}>{status.state === 'muted' ? '恢复麦克风' : '静音'}</button><button disabled={busy} onClick={() => void act(() => controller.current!.stop())}>结束语音</button></> : <button disabled={busy} onClick={() => void act(async () => { const id = session || await create(); activeSession.current = id; await controller.current!.start(id); })}><Icon name="mic" />开启语音陪伴</button>}{error && <p role="alert">{error}</p>}</div>;
}
