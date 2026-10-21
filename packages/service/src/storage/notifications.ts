import { randomUUID } from 'node:crypto';
import { NotificationViewSchema, NotificationBatchSchema, JevDecisionSchema, type NotificationView } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
export class NotificationRepository {
  valid: (value: NotificationView) => boolean = () => true;
  eligible: (value: NotificationView) => boolean = () => true;
  constructor(readonly store: Store, readonly clock = () => Date.now() / 1000) {}
  private decode(body: unknown): NotificationView { return NotificationViewSchema.parse(parseStoredJson(String(body))); }
  put(input: NotificationView): void {
    const value = NotificationViewSchema.parse(input); this.store.run('INSERT OR IGNORE INTO notification VALUES(?,?)',value.id,JSON.stringify(value));
  }
  // Owned by the task settlement transaction; keep delivery identity while revising its result.
  settle(input: NotificationView): void {
    const value = NotificationViewSchema.parse(input), previous = this.get(value.id);
    if (!previous) { this.put(value); return; }
    if (previous.text === value.text) return;
    this.update({ ...previous,text: value.text });
    const row = this.store.connection.prepare('SELECT body FROM jev_decision WHERE notification_id=?').get(value.id);
    if (row) {
      const decision = JevDecisionSchema.parse(parseStoredJson(String(row.body)));
      decision.status = 'stale'; decision.action = 'defer'; decision.not_before = this.clock() + 600; decision.reason = '任务结果已更新，旧判断不再生效';
      this.store.run('UPDATE jev_decision SET body=? WHERE notification_id=?',JSON.stringify(decision),value.id);
    }
  }
  list(): NotificationView[] {
    return this.store.connection.prepare('SELECT body FROM notification ORDER BY rowid DESC LIMIT 500').all().map(row => this.decode(row.body));
  }
  get(id: string): NotificationView | undefined {
    const row = this.store.connection.prepare('SELECT body FROM notification WHERE id=?').get(id); return row ? this.decode(row.body) : undefined;
  }
  pending(): NotificationView[] {
    return this.store.connection.prepare(`SELECT body FROM notification WHERE json_extract(body,'$.status')='pending' OR
      (json_extract(body,'$.status')='leased' AND json_extract(body,'$.lease_until')<=?) ORDER BY rowid`).all(this.clock()).map(row => this.decode(row.body));
  }
  next(quiet: boolean) {
    if (quiet) return null; const now = this.clock();
    return this.store.transaction(() => {
      const pending: NotificationView[] = [];
      for (const row of this.store.connection.prepare('SELECT body FROM notification ORDER BY rowid').all()) {
        const value = this.decode(row.body); if (!this.valid(value)) continue;
        if (value.status === 'leased' && value.lease_until > now) return null;
        if ((value.status === 'pending' || value.status === 'leased' && value.lease_until <= now) && this.eligible(value)) pending.push(value);
      }
      if (!pending.length) return null;
      const batch = randomUUID(); for (const value of pending) {
        value.status = 'leased'; value.batch_id = batch; value.lease_until = now + 15; this.update(value);
      }
      return NotificationBatchSchema.parse({ batch_id: batch,count: pending.length,expires_at: now + 15,
        text: pending.length === 1 ? pending[0]!.text : `有 ${pending.length} 条提醒或任务结果，想看时打开通知收件箱就好。` });
    });
  }
  private update(value: NotificationView): void { this.store.run('UPDATE notification SET body=? WHERE id=?',JSON.stringify(value),value.id); }
  displayed(batch: string, quiet: boolean): boolean {
    if (quiet) return false;
    return this.store.transaction(() => {
      let changed = false;
      for (const row of this.store.connection.prepare('SELECT body FROM notification').all()) {
        const value = this.decode(row.body); if (value.batch_id !== batch || !this.valid(value) || !this.eligible(value)) continue;
        if (['delivered','read'].includes(value.status)) changed = true;
        if (value.status === 'leased' && value.lease_until > this.clock()) {
          value.status = 'delivered'; value.delivered_at = this.clock(); this.update(value); changed = true;
        }
      }
      return changed;
    });
  }
  read(id: string): NotificationView {
    return this.store.transaction(() => {
      const value = this.get(id); if (!value) throw Error('通知不存在');
      if (['missed','cancelled'].includes(value.status)) return value;
      value.status = 'read'; value.delivered_at ||= this.clock(); value.read_at ||= this.clock(); this.update(value); return value;
    });
  }
  cancelFor(id: string): void {
    this.store.transaction(() => {
      for (const row of this.store.connection.prepare('SELECT body FROM notification').all()) {
        const value = this.decode(row.body);
        if (value.delegation_id === id && ['pending','leased'].includes(value.status)) { value.status = 'cancelled'; this.update(value); }
      }
    });
  }
}
