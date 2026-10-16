import type { Page } from './KnowledgePanel';
import type { ChatSession } from '../../../shared/desktop-protocol';
import { Icon } from './Icon';
export function Sidebar({ sessions, selected, page, connected, onCreate, onSelect, onPage }: {
  sessions: ChatSession[]; selected: string; page: string; connected: boolean;
  onCreate: () => void; onSelect: (id: string) => void; onPage: (page: Page) => void;
}) {
  return <aside className="sidebar"><div className="brand">Lobuddy</div>
    <button className="primary new-chat" onClick={onCreate}><Icon name="plus" />新对话</button>
    <nav aria-label="主导航"><button className={page === 'chat' ? 'selected' : ''} onClick={() => onPage('chat')}><Icon name="chat" />对话</button><button className={page === 'tasks' ? 'selected' : ''} onClick={() => onPage('tasks')}><Icon name="tasks" />任务</button>{(['memory', 'skills', 'history', 'progress', 'focus', 'appearance', 'settings'] as const).map(item => <button key={item} className={page === item ? 'selected' : ''} onClick={() => onPage(item)}><Icon name={item} />{{ memory: '记忆', skills: '技能', history: '历史', progress: '成长', settings: '设置', focus: '专注', appearance: '外观' }[item]}</button>)}</nav>
    <section className="recent"><h2>最近对话</h2><div className="session-list">{sessions.map(session => <button key={session.id} className={session.id === selected ? 'selected' : ''} onClick={() => onSelect(session.id!)}><Icon name="chat" /><span>{session.title}</span></button>)}{sessions.length === 0 && <p className="quiet">还没有对话</p>}</div></section>
    <div className="connection" role="status"><span className={connected ? 'dot connected' : 'dot'} />{connected ? '服务已连接' : '服务未连接'}</div>
  </aside>;
}
