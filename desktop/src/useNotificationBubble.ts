import { useEffect, useState } from 'react';
import type { NotificationBatch } from '../../shared/desktop-protocol';
import { request } from './api';

export function useNotificationBubble() {
  const [bubble, setBubble] = useState<NotificationBatch | null>(null);
  useEffect(() => {
    if (document.documentElement.dataset.surface !== 'pet') return;
    let alive = true, busy = false;
    let current: NotificationBatch | null = null;
    let shownUntil = 0;
    const clear = () => { current = null; if (alive) setBubble(null); };
    const poll = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        if (current) {
          const accepted = await request('notification.displayed', { batch_id: current.batch_id });
          if (!accepted.accepted || Date.now() >= shownUntil) clear();
          return;
        }
        const next = await request('notification.next', {});
        if (!alive || document.hidden || !next) return;
        current = next; shownUntil = Date.now() + 8000; setBubble(next);
        // A visible paint precedes delivery acknowledgement. Read status remains explicit.
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        if (!alive || document.hidden) { clear(); return; }
        const accepted = await request('notification.displayed', { batch_id: next.batch_id });
        if (!accepted.accepted) clear();
      } catch { clear(); }
      finally { busy = false; }
    };
    const visibility = () => { if (document.hidden) clear(); };
    document.addEventListener('visibilitychange', visibility);
    void poll(); const timer = setInterval(() => void poll(), 1000);
    return () => { alive = false; clearInterval(timer); document.removeEventListener('visibilitychange', visibility); };
  }, []);
  return bubble;
}
