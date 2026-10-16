import { useRef, useState } from 'react';
import { Icon } from './Icon';
export function Composer({ disabled, onSend }: { disabled: boolean; onSend: (text: string, lane: 'foreground' | 'background') => Promise<void> }) {
  const [text, setText] = useState('');
  const [lane, setLane] = useState<'foreground' | 'background'>('foreground');
  const [sending, setSending] = useState(false);
  const locked = useRef(false);
  const send = async () => {
    if (locked.current || disabled || !text.trim()) return;
    locked.current = true; setSending(true);
    try { await onSend(text, lane); setText(''); }
    finally { locked.current = false; setSending(false); }
  };
  return <form className="composer" onSubmit={event => { event.preventDefault(); void send().catch(() => undefined); }}>
    <textarea aria-label="消息" placeholder="想聊什么，或者想让我帮你做什么？" value={text} maxLength={4000} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send().catch(() => undefined); } }} />
    <div className="composer-actions"><div className="mode" role="group" aria-label="对话模式"><button type="button" aria-pressed={lane === 'foreground'} onClick={() => setLane('foreground')}><Icon name="chat" />聊天</button><button type="button" aria-pressed={lane === 'background'} onClick={() => setLane('background')}><Icon name="work" />后台任务</button></div><button className="primary" type="submit" disabled={disabled || sending || !text.trim()}><Icon name="send" />{sending ? '提交中' : '发送'}</button></div>
  </form>;
}
