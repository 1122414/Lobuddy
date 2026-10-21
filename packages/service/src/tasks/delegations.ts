import { ChatSessionSchema, TurnSendSchema, type DelegationChange, type DelegationEdit, type DelegationConfirm } from '@lobuddy/contracts';
import { ChatRepository } from '../storage/chat.js';
import { NotificationRepository } from '../storage/notifications.js';
import { TaskCoordinator } from './coordinator.js';
export class DelegationService {
  readonly repo;
  constructor(readonly tasks: TaskCoordinator,readonly notifications: NotificationRepository,readonly validateProject: (id: string) => void) { this.repo = tasks.delegations; }
  detail(id: string) {
    const detail = this.repo.detail(id); detail.outcomes = detail.runs.filter(run => run.turn_id).map(run => this.tasks.ledger.outcomes.get(run.turn_id)); return detail;
  }
  async change(id: string,action: string,params: DelegationChange | DelegationConfirm | DelegationEdit) {
    if ('spec' in params && params.spec.project_id) this.validateProject(params.spec.project_id);
    if (action === 'confirm') { const value = this.repo.get(params.delegation_id); if (value.spec.kind === 'reminder' && value.spec.wait.kind === 'user') throw Error('请先确定提醒时间或事件'); }
    const value = this.repo.change(id,action,params);
    if (['cancel','edit'].includes(action)) this.notifications.cancelFor(value.id);
    if (['pause','cancel'].includes(action)) for (const run of this.repo.detail(value.id).runs) {
      if (run.turn_id && ['reserved','running'].includes(run.status)) await this.tasks.cancel(run.turn_id);
    }
    return value;
  }
  async run(requestId: string,params: DelegationChange) {
    const previous = this.repo.replayedRun(requestId,params); if (previous) return previous;
    const value = this.repo.get(params.delegation_id); if (value.spec.project_id) this.validateProject(value.spec.project_id);
    const version = this.tasks.workflows.active(value.spec.kind);
    const { run,created } = this.repo.claim(requestId,params,version.version_id); if (!created) return this.repo.run(run.id);
    try {
      const sessionId = value.spec.session_id || 'delegation-' + value.id;
      if (!this.repo.store.connection.prepare('SELECT 1 FROM chat_session WHERE id=?').get(sessionId)) {
        new ChatRepository(this.repo.store).saveSession(ChatSessionSchema.parse({ id: sessionId,title: [...value.spec.goal].slice(0,100).join('') }));
      }
      await this.tasks.submit('delegation-run-' + run.id,TurnSendSchema.parse({ session_id: sessionId,text: value.spec.goal,lane: 'background',workflow_id: value.spec.kind,
        workflow_input: value.spec.kind === 'source-digest' ? { sources: value.spec.sources } : { source: value.spec.source_directory,output: value.spec.output_directory } }),run.id);
    } catch (error) { this.repo.recover(run.id); throw error; }
    return this.repo.run(run.id);
  }
}
