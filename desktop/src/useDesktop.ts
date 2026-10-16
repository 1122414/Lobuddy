import { useCallback, useEffect, useRef, useState } from 'react';
import type { Approval } from '../../shared/desktop-api';
import type { ChatMessage, ChatSession, TurnState } from '../../shared/desktop-protocol';
import { errorText, request } from './api';

export function useDesktop() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [tasks, setTasks] = useState<TurnState[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selected, setSelected] = useState(sessionStorage.getItem('lobuddy-session') || '');
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const selectedRef = useRef(selected);
  const refreshRef = useRef<() => void>(() => undefined);
  const select = useCallback((id: string) => {
    selectedRef.current = id; sessionStorage.setItem('lobuddy-session', id); setSelected(id); setMessages([]); refreshRef.current();
  }, []);
  useEffect(() => {
    let alive = true;
    let pending = false;
    let loading = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      if (!alive) return;
      if (loading) { pending = true; return; }
      loading = true;
      const selectedAtStart = selectedRef.current;
      try {
        const [newSessions, newTasks, newApprovals, health] = await Promise.all([request('session.list', {}), request('task.list', {}), request('approval.list', {}), request('service.health', {})]);
        if (!alive) return;
        if (!health.model_configured) setError('模型尚未配置，请在项目 .env 中填写模型凭据后重新启动应用。');
        setConnected(true); setSessions(newSessions); setTasks(newTasks); setApprovals(newApprovals);
        if (selectedAtStart === selectedRef.current && !newSessions.some(item => item.id === selectedRef.current)) select(newSessions[0]?.id || '');
        const id = selectedRef.current;
        if (id) {
          const history = await request('session.history', { session_id: id });
          if (alive && selectedRef.current === id) setMessages(history);
        }
      } catch (error) { if (alive) { setConnected(false); setError(errorText(error)); } }
      finally { loading = false; if (pending && alive) { pending = false; schedule(); } }
    };
    const schedule = () => {
      if (timer) return;
      timer = setTimeout(() => { timer = undefined; void refresh(); }, 150);
    };
    refreshRef.current = schedule;
    const stopEvents = window.lobuddy?.subscribe(schedule);
    const stopStatus = window.lobuddy?.onStatus(value => { setConnected(value); if (value) schedule(); });
    void refresh();
    // Reconcile expired approvals and tasks when no renderer event was received.
    const reconcile = setInterval(schedule, 5000);
    return () => { alive = false; clearTimeout(timer); clearInterval(reconcile); stopEvents?.(); stopStatus?.(); };
  }, [select]);
  const perform = async <T,>(action: () => Promise<T>): Promise<T> => {
    try { const result = await action(); setError(''); refreshRef.current(); return result; }
    catch (error) { setError(errorText(error)); throw error; }
  };
  const create = async () => {
    const session = await perform(() => request('session.create', {}));
    select(session.id!);
    return session.id!;
  };
  return { sessions, tasks, messages, approvals, selected, connected, error, select, create,
    send: async (text: string, lane: 'foreground' | 'background') => {
      const id = selectedRef.current || await create();
      // The ID belongs to this submission only. Never auto-retry an uncertain result.
      await perform(() => request('turn.send', { session_id: id, text, lane }));
    },
    cancel: (id: string) => { void perform(() => request('turn.cancel', { turn_id: id })).catch(() => undefined); },
    approve: async (id: string, approved: boolean) => {
      await perform(() => request('approval.resolve', { approval_id: id, approved }));
      setApprovals(value => value.filter(item => item.approval_id !== id));
    },
  };
}
