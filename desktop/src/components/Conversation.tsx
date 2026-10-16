import { useEffect, useRef, useState } from 'react';
import { request } from '../api';
import Markdown from 'react-markdown';
import type { ChatMessage, TurnState } from '../../../shared/desktop-protocol';
import { TaskRow, active } from './TaskList';
function Content({ text }: { text: string }) {
  return <Markdown skipHtml components={{ img: () => null, a: ({ href, children }) => <a href={href} onClick={event => { event.preventDefault(); if (href) void window.lobuddy?.openExternal(href).catch(() => undefined); }}>{children}</a> }}>{text}</Markdown>;
}
function Attachment({ id }: { id: string }) {
  const [preview, setPreview] = useState('');
  useEffect(() => { let alive = true; setPreview('');
    if (/^[a-f0-9]{64}$/.test(id)) void request('image.get', { image_id: id }).then(image => { if (alive) setPreview(image.preview); }).catch(() => undefined);
    return () => { alive = false; };
  }, [id]);
  return preview ? <img className="message-image" src={preview} alt="已发送图片" /> : <p className="quiet">图片暂不可预览</p>;
}
export function Conversation({ messages, tasks, onCancel }: { messages: ChatMessage[]; tasks: TurnState[]; onCancel: (id: string) => void }) {
  const tail = useRef<HTMLDivElement>(null);
  const last = messages.at(-1)?.content;
  const live = tasks.filter(task => active(task) || task.status === 'cancelled').reverse();
  useEffect(() => { tail.current?.scrollIntoView({ block: 'end' }); }, [last, tasks]);
  return <section className="conversation" aria-label="消息历史">
    {!messages.length && !live.length && <div className="empty"><h2>想说什么都可以</h2><p>聊聊今天，或者一起把手边的事做好。</p></div>}
    {messages.map(message => <article key={message.id} className={`message ${message.role}`}><span className="avatar" aria-hidden="true">L</span><div><div className="message-content">{message.image_path && <Attachment id={message.image_path} />}<Content text={message.content} /></div><time>{message.created_at ? new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''}</time></div></article>)}
    {live.map(task => <article key={task.turn_id} className="message assistant"><span className="avatar" aria-hidden="true">L</span><div>{task.output_text && <div className="message-content"><Content text={task.output_text} /></div>}<TaskRow task={task} onCancel={onCancel} /></div></article>)}
    {tasks.filter(task => !active(task) && task.status !== 'cancelled').slice(0, 1).map(task => <div className="completed-task" key={task.turn_id}><TaskRow task={task} onCancel={onCancel} /></div>)}
    <div ref={tail} />
  </section>;
}
