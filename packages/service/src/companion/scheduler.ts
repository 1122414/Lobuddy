import { randomUUID } from 'node:crypto';
import { type RuntimeSettings } from '@lobuddy/contracts';
import { NotificationRepository } from '../storage/notifications.js';
import { ScheduleRepository } from '../storage/schedules.js';
import { NotificationDecisions } from './decisions.js';
import { DelegationService } from '../tasks/delegations.js';
import { TaskCoordinator } from '../tasks/coordinator.js';
import type { createCompanionServices } from '../companion-service.js';
import type { JevClient } from '../engine/jev.js';
export class LocalScheduler {
  readonly notifications: NotificationRepository;
  readonly repo: ScheduleRepository;
  readonly decisions: NotificationDecisions;
  readonly delegations: DelegationService;
  suspended = false;
  private closed = false;
  private timer?: ReturnType<typeof setInterval>;
  private pending?: Promise<void>;
  voiceActive = () => false;
  stopVoice = async () => {};
  constructor(readonly tasks: TaskCoordinator,readonly companion: Awaited<ReturnType<typeof createCompanionServices>>,
    readonly settings: () => RuntimeSettings,credentials: () => { key: string; secrets: string[] },client?: JevClient) {
    this.notifications = new NotificationRepository(tasks.delegations.store);
    this.repo = new ScheduleRepository(tasks.delegations,this.notifications);
    this.delegations = new DelegationService(tasks,this.notifications,id => { companion.projects.scope(id,''); });
    this.notifications.valid = notice => {
      try {
        const value = notice.delegation_id ? tasks.delegations.get(notice.delegation_id) : undefined;
        if (companion.dialogue.blocked(notice.text,Boolean(value?.spec.project_id))) return false;
        return notice.reason !== 'reminder' || !value || !['paused','cancelled','draft','failed','needs_review'].includes(value.status) && Boolean(value.expires_at && Date.now() / 1000 < value.expires_at);
      } catch { return false; }
    };
    this.decisions = new NotificationDecisions(tasks.delegations.store,settings,this.notifications,() => this.quiet(),id => tasks.delegations.get(id).spec.goal,credentials,client);
    this.notifications.eligible = notice => this.decisions.allowed(notice);
  }
  quiet(): boolean {
    return this.closed || this.suspended || this.companion.focus.active || this.companion.companionship.policy.do_not_disturb ||
      this.voiceActive() || this.tasks.activeStates().some(state => state.lane === 'foreground') || this.companion.companionship.engaged;
  }
  start(): void {
    if (this.closed || this.timer) return;
    this.timer = setInterval(() => { void this.tick().catch(() => {}); },1000); this.timer.unref();
  }
  tick(): Promise<void> {
    return this.pending ??= this.run().finally(() => { this.pending = undefined; });
  }
  private async run(): Promise<void> {
    if (this.closed || this.suspended) return;
    const dispatches = this.repo.tick(); this.decisions.poll();
    if (this.quiet() || this.tasks.busy || this.companion.learning.view().state === 'running') return;
    for (const dispatch of dispatches.slice(0,1)) {
      try {
        const value = this.tasks.delegations.get(dispatch.delegationId);
        if (value.status !== 'ready' || value.revision !== dispatch.revision) continue;
        const version = this.tasks.workflows.active(value.spec.kind);
        if (Date.now() / 1000 - value.updated_at > 60) this.tasks.delegations.review(value.id,'已错过自动执行时间，等待你核对后继续');
        else if (version.definition.nodes.some(node => node.kind === 'model')) this.tasks.delegations.review(value.id,'工作流含模型步骤，需要手动继续并计量');
        else await this.delegations.run(dispatch.trigger,{ delegation_id: value.id,revision: dispatch.revision });
      } catch { this.tasks.delegations.review(dispatch.delegationId,'调度条件已变化，未自动重试，请核对范围和授权'); }
      finally { this.repo.dispatched(dispatch.trigger); }
    }
  }
  async power(suspended: boolean): Promise<void> {
    this.suspended = suspended;
    this.companion.discovery.power(suspended);
    if (suspended) {
      await this.decisions.stop(); await this.stopVoice();
      for (const state of this.tasks.activeStates()) await this.tasks.cancel(state.turn_id);
      await this.pending; this.repo.release();
    } else this.repo.event('returned-' + randomUUID(),'app_returned');
  }
  async close(): Promise<void> {
    this.closed = true; if (this.timer) clearInterval(this.timer);
    await this.decisions.stop(true); await this.pending; this.repo.release();
  }
}
