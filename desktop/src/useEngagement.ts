import { useEffect } from 'react';
import { request } from './api';

// Report only engagement inside Lobuddy. Never inspect other apps or send typed text.
export function useEngagement(conversation: boolean) {
  useEffect(() => {
    let typedAt = 0;
    const client = document.documentElement.dataset.surface === 'quick' ? 'quick' : 'manage';
    const update = () => { void request('companionship.activity', { client, typing: document.hasFocus() && Date.now() - typedAt < 8000, conversation: document.hasFocus() && conversation }).catch(() => undefined); };
    const input = () => { typedAt = Date.now(); update(); };
    document.addEventListener('input', input); window.addEventListener('focus', update); window.addEventListener('blur', update);
    const timer = setInterval(update, 2000); update();
    return () => { clearInterval(timer); document.removeEventListener('input', input); window.removeEventListener('focus', update); window.removeEventListener('blur', update); void request('companionship.activity', { client, typing: false, conversation: false }).catch(() => undefined); };
  }, [conversation]);
}
