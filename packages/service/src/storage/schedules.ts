import { createHash, randomUUID } from 'node:crypto';
import { DelegationViewSchema, DelegationRunSchema, NotificationViewSchema, ScheduleViewSchema, type DelegationView } from '@lobuddy/contracts';
import { delegationJson, nextOccurrence, stableIdentity } from '@lobuddy/domain';
import { DelegationRepository } from './delegations.js';
import { NotificationRepository } from './notifications.js';
import { parseStoredJson } from './json.js';
type Dispatch = { delegationId: string; revision: number; trigger: string };
export class ScheduleRepository {
  readonly owner = randomUUID().replaceAll('-','');
  readonly store;
  constructor(readonly delegations: DelegationRepository, readonly notifications: NotificationRepository,readonly clock = () => Date.now() / 1000) {
    this.store = delegations.store;
  }
  event(id: string, kind: string, subject = ''): void {
    if (!['app_returned','focus_finished','delegation_completed'].includes(kind)) throw Error('不支持的内部事件');
    this.store.run('INSERT OR IGNORE INTO delegation_event VALUES(?,?,?,?)',id,kind,subject,this.clock());
  }
  release(): void { this.store.run('DELETE FROM schedule_owner WHERE id=1 AND owner=?',this.owner); }
  private lease(): boolean {
    const row = this.store.connection.prepare('SELECT owner,expires FROM schedule_owner WHERE id=1').get();
    if (row && row.owner !== this.owner && Number(row.expires) > this.clock()) return false;
    this.store.run('INSERT INTO schedule_owner VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',this.owner,this.clock() + 10);
    return true;
  }
  private save(value: DelegationView): void { value.revision++; value.updated_at = this.clock(); this.delegations.write(value); }
  private fire(value: DelegationView, trigger: string, planned: number): void {
    const now = this.clock();
    if (value.spec.kind !== 'reminder') {
      if (value.spec.kind === 'organize-files' || now - planned > 60) {
        value.status = 'needs_review'; value.reason = '文件写入或逾期执行需重新确认，不自动补跑'; this.save(value); return;
      }
      value.status = 'ready'; value.reason = '已到约定时间，准备受控只读任务'; this.save(value);
      this.store.run('INSERT OR IGNORE INTO schedule_dispatch(trigger_id,delegation_id,revision) VALUES(?,?,?)',trigger,value.id,value.revision); return;
    }
    const missed = value.spec.repeat.frequency === 'once' && now - planned > 86400 || !value.spec.repeat.catch_up && now - planned > 60;
    const id = stableIdentity(trigger); if (this.store.connection.prepare('SELECT 1 FROM notification WHERE id=?').get(id)) return;
    const run = DelegationRunSchema.parse({ id,delegation_id: value.id,revision: value.revision + 1,trigger_id: trigger,workflow_version: 'notification',
      created_at: now,status: missed ? 'completed' : 'running',reason: missed ? '已错过，不补弹提醒' : '通知已保存，尚未投递',finished_at: missed ? now : null });
    const notice = NotificationViewSchema.parse({ id,reason: 'reminder',source_id: run.id,delegation_id: value.id,
      text: value.spec.goal + (now - planned > 60 ? `（延迟约 ${Math.max(1,Math.trunc((now - planned) / 60))} 分钟）` : ''),
      planned_at: planned,created_at: now,status: missed ? 'missed' : 'pending' });
    this.notifications.put(notice); this.store.run('INSERT INTO delegation_run VALUES(?,?,?,NULL,?)',run.id,value.id,trigger,JSON.stringify(run));
    if (value.spec.repeat.frequency !== 'once' && missed) {
      const cursor = this.store.connection.prepare('SELECT next_at FROM delegation_schedule WHERE id=?').get(value.id);
      if (cursor && cursor.next_at === null) value.status = 'needs_review';
    }
    if (value.spec.repeat.frequency === 'once') { value.status = missed ? 'needs_review' : 'waiting_user'; value.active_run_id = missed ? '' : run.id; }
    value.reason = run.reason; this.save(value);
  }
  tick(): Dispatch[] {
    const leased = this.store.transaction(() => {
      if (!this.lease()) return false;
      for (const row of this.store.connection.prepare('SELECT body FROM delegation').all()) {
        const value = DelegationViewSchema.parse(parseStoredJson(String(row.body)));
        if (value.status === 'completed' && value.spec.repeat.frequency !== 'once') {
          const cursor = this.store.connection.prepare('SELECT next_at FROM delegation_schedule WHERE id=?').get(value.id);
          if (cursor && cursor.next_at !== null) { value.status = 'scheduled'; value.reason = '本次结果已验证，等待下次约定时间'; this.save(value); }
        }
        if (!['scheduled','waiting_event'].includes(value.status)) continue;
        const now = this.clock();
        if (!value.expires_at || value.expires_at <= now) {
          value.status = 'needs_review'; value.reason = '授权已到期，等待你决定是否重新安排'; this.save(value); continue;
        }
        const wait = value.spec.wait;
        if (wait.kind === 'time') {
          const signature = createHash('sha256').update(delegationJson(value.spec)).digest('hex');
          const entry = this.store.connection.prepare('SELECT signature,next_at FROM delegation_schedule WHERE id=?').get(value.id);
          let due: number | null;
          if (!entry || entry.signature !== signature) {
            this.store.run('INSERT INTO delegation_schedule VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET signature=excluded.signature,next_at=excluded.next_at',value.id,signature,wait.at);
            due = wait.at;
          } else due = entry.next_at === null ? null : Number(entry.next_at);
          if (due === null || due > now) continue;
          if (value.spec.repeat.end_at !== null && due > value.spec.repeat.end_at) { value.status = 'completed'; value.reason = '已到周期提醒结束时间'; this.save(value); continue; }
          // Python float string uses .0 for whole-second instants; preserve old trigger identity.
          const instant = Number.isInteger(due) ? `${due}.0` : String(due);
          const trigger = `due:${value.id}:${signature}:${instant}`;
          this.store.run('UPDATE delegation_schedule SET next_at=? WHERE id=?',nextOccurrence(value.spec.repeat,wait.timezone,now),value.id);
          this.fire(value,trigger,due);
        } else if (wait.kind === 'event') {
          const events = this.store.connection.prepare(`SELECT * FROM delegation_event e WHERE kind=? AND subject=? AND at>=?
            AND NOT EXISTS(SELECT 1 FROM delegation_event_consumed c WHERE c.delegation_id=? AND c.event_id=e.id) ORDER BY at DESC LIMIT 1`)
            .all(wait.event,wait.subject_id,value.authorized_at || now,value.id);
          for (const event of events) {
            this.store.run('INSERT INTO delegation_event_consumed VALUES(?,?)',value.id,event.id!);
            this.fire(value,`event:${value.id}:${event.id}`,Number(event.at));
          }
        }
      }
      return true;
    });
    if (!leased) return [];
    this.completeDeliveries();
    return this.store.connection.prepare('SELECT * FROM schedule_dispatch WHERE done=0').all().map(row => ({ delegationId: String(row.delegation_id),revision: Number(row.revision),trigger: String(row.trigger_id) }));
  }
  dispatched(trigger: string): void { this.store.run('UPDATE schedule_dispatch SET done=1 WHERE trigger_id=?',trigger); }
  completeDeliveries(): void {
    this.store.transaction(() => {
      for (const row of this.store.connection.prepare('SELECT body FROM notification').all()) {
        const notice = NotificationViewSchema.parse(parseStoredJson(String(row.body)));
        if (notice.reason !== 'reminder' || !['delivered','read'].includes(notice.status)) continue;
        const result = this.store.connection.prepare('SELECT body FROM delegation_run WHERE id=?').get(notice.source_id); if (!result) continue;
        const run = DelegationRunSchema.parse(parseStoredJson(String(result.body))); if (run.status === 'completed') continue;
        const value = this.delegations.get(run.delegation_id); if (['paused','cancelled','draft'].includes(value.status)) continue;
        run.status = 'completed'; run.verdict = 'verified'; run.finished_at = this.clock(); run.reason = '通知已投递；用户是否已读单独记录';
        this.store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify(run),run.id);
        if (value.spec.repeat.frequency === 'once') { value.status = 'completed'; value.active_run_id = ''; }
        else {
          const entry = this.store.connection.prepare('SELECT next_at FROM delegation_schedule WHERE id=?').get(value.id);
          if (entry && entry.next_at === null) value.status = 'completed';
        }
        value.reason = run.reason; this.save(value); this.delegations.recordCompletion(run);
      }
    });
  }
  view(id: string) {
    const value = this.delegations.get(id), row = this.store.connection.prepare('SELECT next_at FROM delegation_schedule WHERE id=?').get(id);
    return ScheduleViewSchema.parse({ delegation_id: id,next_at: row ? row.next_at : value.spec.wait.at,
      timezone: value.spec.wait.timezone,repeat: value.spec.repeat,state: value.status,reason: value.reason });
  }
}
