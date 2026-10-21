import { OutcomeSchema, localTimestamp, type Outcome } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';

export class OutcomeRepository {
  constructor(private readonly store: Store) {}
  get(id: string): Outcome {
    const row = this.store.connection.prepare('SELECT body FROM task_acceptance WHERE turn_id=?').get(id);
    return OutcomeSchema.parse(row ? parseStoredJson(String(row.body)) : { turn_id: id });
  }
  save(input: Outcome): void {
    let outcome = OutcomeSchema.parse(input); const previous = this.get(outcome.turn_id);
    if (!['chat', outcome.scenario].includes(previous.scenario) && outcome.scenario !== 'chat') {
      const verdicts = [previous.verdict, outcome.verdict];
      outcome = OutcomeSchema.parse({ turn_id: outcome.turn_id, scenario: 'multiple',
        verdict: verdicts.includes('failed') ? 'failed' : verdicts.includes('unknown') ? 'unknown' : 'verified',
        criteria: [...new Set([...previous.criteria, ...outcome.criteria])], evidence: [...previous.evidence, ...outcome.evidence],
        reason: `${previous.reason}；${outcome.reason}` });
    }
    this.store.run('INSERT INTO task_acceptance VALUES(?,?,?) ON CONFLICT(turn_id) DO UPDATE SET body=excluded.body',
      outcome.turn_id, JSON.stringify(outcome), localTimestamp());
  }
  claimEffect(id: string, turnId: string, body: string): void {
    this.store.transaction(() => {
      if (this.store.connection.prepare('SELECT 1 FROM task_effect WHERE id=? OR turn_id=?').get(id, turnId)) throw Error('该写操作已执行或结果未知，不能自动重放');
      this.store.run("INSERT INTO task_effect VALUES(?,?,'started',?)", id, turnId, body);
    });
  }
  finishEffect(id: string, state: 'completed' | 'failed' | 'unknown'): void {
    this.store.run('UPDATE task_effect SET state=? WHERE id=?', state, id);
  }
  finishTurn(turnId: string, status: string): Outcome {
    const outcome = this.get(turnId);
    if (['cancelled', 'interrupted'].includes(status)) {
      outcome.verdict = 'unknown'; outcome.reason = '执行已取消或中断；已发生的副作用不会自动撤销';
    }
    this.save(outcome); return outcome;
  }
}
