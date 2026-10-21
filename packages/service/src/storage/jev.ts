import { Temporal } from '@js-temporal/polyfill';
import { JevDecisionSchema, type JevDecision } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
export class JevRepository {
  constructor(readonly store: Store) {
    store.transaction(() => {
      for (const row of store.connection.prepare('SELECT notification_id,body FROM jev_decision').all()) {
        const value = JevDecisionSchema.parse(parseStoredJson(String(row.body)));
        if (value.status === 'running') { value.status = 'interrupted'; value.reason = '上次判断中断，未自动重试'; this.finish(String(row.notification_id),value); }
      }
    });
  }
  day(now: number): string { return Temporal.Instant.fromEpochMilliseconds(Math.trunc(now * 1000)).toZonedDateTimeISO('Asia/Shanghai').toPlainDate().toString(); }
  get(id: string): JevDecision | undefined {
    const row = this.store.connection.prepare('SELECT body FROM jev_decision WHERE notification_id=?').get(id);
    return row ? JevDecisionSchema.parse(parseStoredJson(String(row.body))) : undefined;
  }
  usage(now: number): { calls: number; bytes: number } {
    const row = this.store.connection.prepare('SELECT calls,request_bytes FROM jev_budget WHERE day=?').get(this.day(now));
    return { calls: Number(row?.calls ?? 0),bytes: Number(row?.request_bytes ?? 0) };
  }
  reserve(id: string, hash: string, value: JevDecision, size: number, dailyCalls: number, dailyBytes: number): boolean {
    if (!Number.isSafeInteger(size) || size < 0) throw Error('请求预算无效');
    return this.store.transaction(() => {
      if (this.get(id)) return false;
      const day = this.day(value.created_at); this.store.run('INSERT OR IGNORE INTO jev_budget VALUES(?,0,0)',day);
      const used = this.usage(value.created_at), accepted = used.calls < dailyCalls && used.bytes + size <= dailyBytes;
      if (accepted) this.store.run('UPDATE jev_budget SET calls=calls+1,request_bytes=request_bytes+? WHERE day=?',size,day);
      else { value.status = 'fallback'; value.reason = '今日 Jev 预算已用完，延后合并'; }
      this.store.run('INSERT INTO jev_decision VALUES(?,?,?)',id,hash,JSON.stringify(JevDecisionSchema.parse(value))); return accepted;
    });
  }
  finish(id: string, value: JevDecision): void {
    this.store.run('UPDATE jev_decision SET body=? WHERE notification_id=?',JSON.stringify(JevDecisionSchema.parse(value)),id);
  }
  recent(): JevDecision[] {
    return this.store.connection.prepare('SELECT body FROM jev_decision ORDER BY rowid DESC LIMIT 10').all().map(row => JevDecisionSchema.parse(parseStoredJson(String(row.body))));
  }
}
