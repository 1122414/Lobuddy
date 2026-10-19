import { NotificationsPanel } from './components/NotificationsPanel';
import { DelegationsPanel } from './components/DelegationsPanel';
import { useEngagement } from './useEngagement';
import { CompanionshipPanel } from './components/CompanionshipPanel';
import { useCompanion } from './companion';
import { CompanionPanel, FocusPanel } from './components/CompanionPanel';
import { KnowledgePanel, type Page } from './components/KnowledgePanel';
import { ProgressPanel } from './components/ProgressPanel';
import { SettingsPanel } from './components/SettingsPanel';
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
  useCompanion();
  const [page, setPage] = useState<Page>('chat');
  useEngagement(page === 'chat');
  const select = (id: string) => { state.select(id); setPage('chat'); };
  const title = page !== 'chat' ? { notifications: '通知', delegations: '托付给她的事', tasks: '任务', memory: '记忆', skills: '技能', history: '历史', progress: '成长', settings: '设置', focus: '专注', appearance: '外观', companionship: '陪伴' }[page] : state.sessions.find(session => session.id === state.selected)?.title || '新对话';
  return <div className="shell"><Sidebar {...state} page={page} onSelect={select} onCreate={() => { void state.create().then(() => setPage('chat')).catch(() => undefined); }} onPage={setPage} />
    <main><header className="page-header"><h1>{title}</h1><span>一起慢慢来</span></header>
      {state.error && <div className="error" role="alert">{state.error}</div>}
      {page === 'notifications' ? <NotificationsPanel /> : page === 'delegations' ? <DelegationsPanel /> : page === 'chat' ? <><Conversation sessionId={state.selected} messages={state.messages} tasks={state.tasks.filter(task => task.session_id === state.selected)} onCancel={state.cancel} /><Composer key={state.selected} disabled={!state.connected} onSend={state.send} /></> : page === 'tasks' ? <TaskList tasks={state.tasks} onCancel={state.cancel} onSelect={select} /> : page === 'history' ? <HistoryPanel sessionId={state.selected} onSelect={select} /> : page === 'progress' ? <ProgressPanel /> : page === 'companionship' ? <CompanionshipPanel /> : page === 'focus' ? <FocusPanel /> : page === 'appearance' ? <CompanionPanel /> : page === 'settings' ? <SettingsPanel /> : <KnowledgePanel key={page} page={page} />}
    </main><ApprovalDialog approval={state.approvals[0]} onResolve={state.approve} />
  </div>;
}
