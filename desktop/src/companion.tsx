import { useEffect, useRef, useState } from 'react';
import type { CompanionPreferences, TurnState } from '../../shared/desktop-protocol';
import type { Focus } from '../../shared/desktop-api';
import { errorText, request } from './api';
import { ApprovalDialog } from './components/ApprovalDialog';
import { Composer } from './components/Composer';
import { Conversation } from './components/Conversation';
import { Icon } from './components/Icon';
import { useDesktop } from './useDesktop';

export type PetActivity = 'quiet' | 'listening' | 'thinking' | 'speaking' | 'executing' | 'approval' | 'error';
const labels: Record<PetActivity, string> = { quiet: '安静', listening: '倾听', thinking: '思考', speaking: '说话', executing: '执行', approval: '待审批', error: '异常' };
const rows: Record<PetActivity, [number, number[]]> = {
  quiet: [0, [280, 110, 110, 140, 140, 320]], listening: [6, [150, 150, 150, 150, 150, 260]],
  thinking: [7, [120, 120, 120, 120, 120, 220]], executing: [7, [120, 120, 120, 120, 120, 220]],
  speaking: [3, [140, 140, 140, 280]], approval: [8, [150, 150, 150, 150, 150, 280]],
  error: [5, [140, 140, 140, 140, 140, 140, 140, 240]],
};
function readable(color: string) {
  const rgb = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722 > .179 ? '#142c36' : '#ffffff';
}
export function useCompanion() {
  const [preferences, setPreferences] = useState<CompanionPreferences>({});
  const [name, setName] = useState('Lobuddy');
  const [activity, setActivity] = useState<PetActivity>('quiet');
  const [focus, setFocus] = useState<Focus>({ state: 'idle', seconds_remaining: 0 });
  const [bubble, setBubble] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true, loading = false, initialized = false, completedFocus: number | undefined;
    let previous = new Map<string, string>();
    let bubbleTimer: ReturnType<typeof setTimeout>;
    const showBubble = (text: string) => { clearTimeout(bubbleTimer); setBubble(text); bubbleTimer = setTimeout(() => { if (alive) setBubble(''); }, 8000); };
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const [config, pet, tasks, approvals, timer] = await Promise.all([request('companion.get', {}), request('pet.get', {}), request('task.list', {}), request('approval.list', {}), request('focus.get', {})]);
        if (!alive) return;
        if (completedFocus !== undefined && (timer.completed_count ?? 0) > completedFocus) showBubble('这轮专注完成啦，休息一下吧。');
        completedFocus = timer.completed_count;
        setPreferences(config); setName(pet.name || 'Lobuddy'); setFocus(timer); setError('');
        setActivity(approvals.length ? 'approval' : tasks.some(task => task.status === 'running' && task.lane === 'foreground') ? 'thinking' : tasks.some(task => ['running', 'queued'].includes(task.status)) ? 'executing' : 'quiet');
        const terminal = tasks.find(task => previous.has(task.turn_id) && previous.get(task.turn_id) !== task.status && ['completed', 'failed', 'interrupted'].includes(task.status));
        if (terminal) showBubble(terminal.status === 'completed' ? '事情做好啦，点击查看结果。' : '这次没完成，点击查看原因。');
        if (!initialized) { initialized = true; showBubble('我在这里。'); }
        previous = new Map(tasks.map(task => [task.turn_id, task.status]));
        document.documentElement.style.setProperty('--on-accent', readable(config.accent || '#367572'));
        document.documentElement.style.setProperty('--on-side', readable(config.side || '#deebec'));
        document.documentElement.style.setProperty('--accent', config.accent || '#367572');
        document.documentElement.style.setProperty('--side', config.side || '#deebec');
      } catch (error) { if (alive) { setError(errorText(error)); setActivity('error'); } }
      finally { loading = false; }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 1000);
    return () => { alive = false; clearInterval(timer); clearTimeout(bubbleTimer); };
  }, []);
  return { preferences, name, activity, focus, bubble, error };
}
export function PetSprite({ preferences, activity }: { preferences: CompanionPreferences; activity: PetActivity }) {
  const [frame, setFrame] = useState(0);
  const [failedImage, setFailedImage] = useState('');
  const [row, durations] = rows[activity];
  const scale = preferences.scale ?? 1;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>, index = 0;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    const tick = () => { setFrame(index); timer = setTimeout(() => { index = (index + 1) % durations.length; tick(); }, durations[index]); };
    const update = () => { clearTimeout(timer); index = 0; setFrame(0); if (!motion.matches && !document.hidden) tick(); };
    update(); motion.addEventListener('change', update); document.addEventListener('visibilitychange', update);
    return () => { clearTimeout(timer); motion.removeEventListener('change', update); document.removeEventListener('visibilitychange', update); };
  }, [durations]);
  return preferences.sprite === 'custom' && preferences.image_id && failedImage !== preferences.image_id ? <img className="pet-custom" onError={() => setFailedImage(preferences.image_id || '')} draggable={false} alt="自定义伙伴" src={`lobuddy://pet-asset/${preferences.image_id}`} style={{ width: 144 * scale, height: 156 * scale, opacity: preferences.opacity }} /> : <div role="img" aria-label="浊蒂" title={failedImage && failedImage === preferences.image_id ? "自定义外观暂不可读取，已显示浊蒂；可在外观中重新选择。" : undefined} className="pet-sprite" style={{ width: 144 * scale, height: 156 * scale, opacity: preferences.opacity, backgroundImage: `url(/pets/${preferences.sprite === 'skadi' ? 'skadi' : 'skadi-v2'}.webp)`, backgroundSize: `${1152 * scale}px ${1716 * scale}px`, backgroundPosition: `${-Math.min(frame, durations.length - 1) * 144 * scale}px ${-row * 156 * scale}px` }} />;
}
export function PetSurface() {
  const state = useCompanion();
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const call = (action: 'chat' | 'drag-start' | 'drag-move' | 'drag-end') => { void window.lobuddy?.windowAction(action).catch(() => undefined); };
  const previousHit = useRef(false);
  const hit = (interactive: boolean) => { if (previousHit.current === interactive) return; previousHit.current = interactive; void window.lobuddy?.petHitTest(interactive).catch(() => undefined); };
  return <div className="pet-surface" onPointerMove={event => { if (!drag.current) hit(!!(event.target as Element).closest('[data-pet-hit]')); }}>
    <div className="pet-bubble-space">{(state.bubble || state.activity === 'approval' || state.error) && <button data-pet-hit className="pet-bubble" onPointerEnter={() => hit(true)} onPointerLeave={() => hit(false)} onClick={() => call('chat')}>{state.error ? '服务断开了，点击看看。' : state.activity === 'approval' ? '有件事需要你确认。' : state.bubble}</button>}</div>
    <button className="pet-touch" data-pet-hit aria-label="打开快速聊天，拖动可移动桌宠" onPointerEnter={() => hit(true)} onPointerLeave={() => { if (!drag.current) hit(false); }}
      onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.screenX, y: event.screenY, moved: false }; call('drag-start'); }}
      onPointerMove={event => { if (drag.current) { if (Math.hypot(event.screenX - drag.current.x, event.screenY - drag.current.y) > 4) drag.current.moved = true; if (drag.current.moved) call('drag-move'); } }}
      onPointerUp={() => { const moved = drag.current?.moved; drag.current = null; call('drag-end'); if (!moved) call('chat'); }}
      onPointerCancel={() => { drag.current = null; call('drag-end'); }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') call('chat'); }}><PetSprite preferences={state.preferences} activity={state.activity} /></button>
    <span className="pet-label">{state.focus.state === 'focusing' ? '陪你专注' : labels[state.activity]}</span>
  </div>;
}
export function QuickChat() {
  const state = useDesktop();
  const companion = useCompanion();
  const background = state.tasks.filter((task: TurnState) => task.lane === 'background' && ['queued', 'running'].includes(task.status));
  return <div className="quick-chat"><header><h1>{companion.name}</h1><button aria-label="展开管理窗口" onClick={() => { void window.lobuddy?.windowAction('manage'); }}><Icon name="expand" /></button><button aria-label="关闭快速聊天" onClick={() => { void window.lobuddy?.windowAction('hide'); }}><Icon name="close" /></button></header>
    {state.error && <div className="error" role="alert">{state.error}</div>}
    <Conversation compact messages={state.messages} tasks={state.tasks.filter(task => task.session_id === state.selected)} onCancel={state.cancel} />
    <div className="quick-task"><Icon name="work" />{background.length ? `${background.length} 个后台任务进行中` : '暂时没有后台任务'}</div>
    <Composer compact key={state.selected} disabled={!state.connected} onSend={state.send} />
    <ApprovalDialog approval={state.approvals[0]} onResolve={state.approve} />
  </div>;
}
