import { useEffect, useState } from 'react';
import { request } from '../api';
import type { Outcome } from '../../../shared/desktop-protocol';
import type { TurnState } from '../../../shared/desktop-protocol';
import { Icon } from './Icon';
export const statusText: Record<TurnState['status'], string> = { queued: '排队中', running: '执行中', completed: '执行结束', cancelled: '已取消', failed: '失败', interrupted: '已中断' };
export const active = (task: TurnState) => task.status === 'queued' || task.status === 'running';
export function TaskRow({ task, onCancel, onSelect }: { task: TurnState; onCancel: (id: string) => void; onSelect?: () => void }) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  useEffect(() => { let alive = true; if (!active(task)) void request('task.outcome', {turn_id: task.turn_id}).then(value => {if (alive) setOutcome(value);}).catch(() => undefined); return () => {alive=false;}; }, [task.turn_id, task.status]);
  return <div className="task-row" data-status={task.status}><Icon name={task.status === 'completed' ? 'tasks' : 'work'} /><div className="task-label">{onSelect ? <button onClick={onSelect}>{task.input_text}</button> : <span>{task.input_text}</span>}{outcome && <details><summary>{outcome.verdict === 'verified' ? '结果已验证' : outcome.verdict === 'failed' ? '验收未通过' : '结果未验证'}</summary><p>{outcome.reason}</p>{outcome.criteria?.map(item => <p key={item}>{item}</p>)}<pre>{JSON.stringify(outcome.evidence, null, 2)}</pre></details>}{task.error && <p role="alert">{task.error}</p>}</div><span className="task-status">{statusText[task.status]}</span>{active(task) && <button className="cancel" onClick={() => onCancel(task.turn_id)}>取消</button>}</div>;
}
export function TaskList({ tasks, onCancel, onSelect }: { tasks: TurnState[]; onCancel: (id: string) => void; onSelect: (id: string) => void }) {
  return <section className="task-list" aria-label="任务列表">{tasks.length ? tasks.map(task => <TaskRow key={task.turn_id} task={task} onCancel={onCancel} onSelect={() => onSelect(task.session_id)} />) : <div className="empty"><h2>这里会留下每一次进展</h2><p>你交给我的任务，可以在这里查看或取消。</p></div>}</section>;
}
