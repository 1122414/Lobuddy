import { useRef, useState } from 'react';
import type { ImageInfo } from '../../../shared/desktop-protocol';
import { Icon } from './Icon';
export function Composer({ disabled, onSend }: { disabled: boolean; onSend: (text: string, lane: 'foreground' | 'background', imageId?: string) => Promise<void> }) {
  const [image, setImage] = useState<ImageInfo | null>(null);
  const [imageError, setImageError] = useState('');
  const [text, setText] = useState('');
  const [lane, setLane] = useState<'foreground' | 'background'>('foreground');
  const [sending, setSending] = useState(false);
  const locked = useRef(false);
  const send = async () => {
    if (locked.current || disabled || !text.trim()) return;
    locked.current = true; setSending(true);
    try { await onSend(text, lane, image?.image_id); setText(''); setImage(null); }
    finally { locked.current = false; setSending(false); }
  };
  return <form className="composer" onSubmit={event => { event.preventDefault(); void send().catch(() => undefined); }}>
    {image && <div className="image-selection"><img src={image.preview} alt="待发送图片" /><button type="button" onClick={() => setImage(null)}>移除图片</button></div>}
    {imageError && <p role="alert">{imageError}</p>}
    <textarea aria-label="消息" placeholder="想聊什么，或者想让我帮你做什么？" value={text} maxLength={4000} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send().catch(() => undefined); } }} />
    <div className="composer-actions"><button type="button" disabled={disabled || sending} onClick={() => { setImageError(''); void (window.lobuddy ? window.lobuddy.pickImage() : Promise.reject(Error('请在桌面应用中使用'))).then(value => { if (value) setImage(value); }).catch(() => setImageError('图片无法读取，请确认格式、大小和尺寸。')); }}>添加图片</button><div className="mode" role="group" aria-label="对话模式"><button type="button" aria-pressed={lane === 'foreground'} onClick={() => setLane('foreground')}><Icon name="chat" />聊天</button><button type="button" aria-pressed={lane === 'background'} onClick={() => setLane('background')}><Icon name="work" />后台任务</button></div><button className="primary" type="submit" disabled={disabled || sending || !text.trim()}><Icon name="send" />{sending ? '提交中' : '发送'}</button></div>
  </form>;
}
