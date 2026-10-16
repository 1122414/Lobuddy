import { KnowledgePanel, type Page } from './components/KnowledgePanel';
import { HistoryPanel } from './components/HistoryPanel';
import { useState } from 'react';
import { ApprovalDialog } from './components/ApprovalDialog';
import { Composer } from './components/Composer';
import { Conversation } from './components/Conversation';
import { Sidebar } from './components/Sidebar';
import { TaskList } from './components/TaskList';
import { useDesktop } from './useDesktop';
export function App() {
  const state = useDesktop();
  const [page, setPage] = useState<Page>('chat');
  const select = (id: string) => { state.select(id); setPage('chat'); };
  const title = page !== 'chat' ? { tasks: '任务', memory: '记忆', skills: '技能', history: '历史' }[page] : state.sessions.find(session => session.id === state.selected)?.title || '新对话';
  return <div className="shell"><Sidebar {...state} page={page} onSelect={select} onCreate={() => { void state.create().then(() => setPage('chat')).catch(() => undefined); }} onPage={setPage} />
    <main><header className="page-header"><h1>{title}</h1><span>一起慢慢来</span></header>
      {state.error && <div className="error" role="alert">{state.error}</div>}
      {page === 'chat' ? <><Conversation messages={state.messages} tasks={state.tasks.filter(task => task.session_id === state.selected)} onCancel={state.cancel} /><Composer key={state.selected} disabled={!state.connected} onSend={state.send} /></> : page === 'tasks' ? <TaskList tasks={state.tasks} onCancel={state.cancel} onSelect={select} /> : page === 'history' ? <HistoryPanel sessionId={state.selected} onSelect={select} /> : <KnowledgePanel key={page} page={page} />}
    </main><ApprovalDialog approval={state.approvals[0]} onResolve={state.approve} />
  </div>;
}
