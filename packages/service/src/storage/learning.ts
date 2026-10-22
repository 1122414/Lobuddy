import { LearningBudgetSchema, LearningJobViewSchema, type LearningPolicy } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
export type Reservation = { calls: number; input_tokens: number; output_tokens: number };
export type LearningClaim = { id: string; source: string; attempt: number; day: string; reservation: Reservation };
export class LearningRepository {
  constructor(readonly store: Store) { store.run('INSERT OR IGNORE INTO learning_schema VALUES(1)'); }
  day(now: number): string {
    const date = new Date(now * 1000);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }
  recover(now: number): void {
    this.store.run("UPDATE learning_job SET status='interrupted',updated_at=?,error='上次运行中断，保留预算；等待安全处理' WHERE status='running'", now);
  }
  enqueue(kind: string, source: string, now: number): void {
    this.store.run('INSERT OR IGNORE INTO learning_job(id,kind,source_id,updated_at) VALUES(?,?,?,?)', `${kind}:${source}`,kind,source,now);
  }
  usage(now: number) {
    const day = this.day(now), row = this.store.connection.prepare('SELECT * FROM learning_budget WHERE day=?').get(day);
    return LearningBudgetSchema.parse(row ?? { day });
  }
  jobs() {
    return this.store.connection.prepare('SELECT * FROM learning_job ORDER BY updated_at DESC,id LIMIT 30').all()
      .map(row => LearningJobViewSchema.parse({ ...row, result: parseStoredJson(String(row.result)) }));
  }
  canReserve(now: number, policy: LearningPolicy, amount: Reservation): boolean {
    if ([amount.calls,amount.input_tokens,amount.output_tokens].some(n => !Number.isSafeInteger(n) || n < 0)) throw Error('预算预留不能为负数或非整数');
    const used = this.usage(now);
    return policy.enabled && (!amount.calls || used.calls + amount.calls <= policy.daily_calls) &&
      (!amount.input_tokens || used.input_tokens + amount.input_tokens <= policy.daily_input_tokens) &&
      (!amount.output_tokens || used.output_tokens + amount.output_tokens <= policy.daily_output_tokens);
  }
  claim(kind: string, now: number, policy: LearningPolicy, amount: Reservation): LearningClaim | undefined {
    return this.store.transaction(() => {
      if (!this.canReserve(now, policy, amount)) return;
      const row = this.store.connection.prepare(`SELECT id,source_id,attempts FROM learning_job WHERE kind=? AND attempts<3
        AND (status='pending' OR (status IN ('interrupted','failed') AND updated_at<=?)) ORDER BY updated_at,id LIMIT 1`).get(kind,now - 300);
      if (!row) return;
      const day = this.day(now); this.store.run('INSERT OR IGNORE INTO learning_budget(day) VALUES(?)', day);
      this.store.run('UPDATE learning_budget SET calls=calls+?,input_tokens=input_tokens+?,output_tokens=output_tokens+? WHERE day=?',
        amount.calls,amount.input_tokens,amount.output_tokens,day);
      this.store.run("UPDATE learning_job SET status='running',attempts=attempts+1,updated_at=?,error='' WHERE id=?", now,row.id!);
      return { id: String(row.id), source: String(row.source_id), attempt: Number(row.attempts) + 1, day,
        reservation: { calls: amount.calls,input_tokens: amount.input_tokens,output_tokens: amount.output_tokens } };
    });
  }
  finish(claim: LearningClaim, status: 'completed' | 'failed' | 'interrupted', now: number, result = '{}', error = '', unused = false): void {
    this.store.transaction(() => {
      const changed = this.store.run("UPDATE learning_job SET status=?,updated_at=?,result=?,error=? WHERE id=? AND status='running' AND attempts=?",
        status,now,result,error,claim.id,claim.attempt).changes;
      if (!changed || status !== 'completed' || !unused) return;
      // Only the current attempt's provably untouched reservation is releasable, on its original day.
      const { calls,input_tokens,output_tokens } = claim.reservation;
      if (this.store.run(`UPDATE learning_budget SET calls=calls-?,input_tokens=input_tokens-?,output_tokens=output_tokens-?
        WHERE day=? AND calls>=? AND input_tokens>=? AND output_tokens>=?`,
      calls,input_tokens,output_tokens,claim.day,calls,input_tokens,output_tokens).changes !== 1) throw Error('后台预留额度不一致');
    });
  }
}
