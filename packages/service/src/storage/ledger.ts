import { PetStateSchema, PetProgressEventSchema, ObservedUsageSchema, ProgressOverviewSchema, localTimestamp,
  type TurnState, type ServiceEvent, type PetProgressEvent } from '@lobuddy/contracts';
import { ABILITIES, availableAbilities, difficulty, requiredExp, rewardCompletion } from '@lobuddy/domain';
import { Store } from './database.js';
import { PetRepository } from './pet.js';
import { TurnRepository } from './turns.js';
import { OutcomeRepository } from './outcomes.js';
import { parseStoredJson } from './json.js';

export class RuntimeLedger {
  readonly outcomes: OutcomeRepository;
  private readonly pet: PetRepository;
  constructor(private readonly store: Store, private readonly turns: TurnRepository) {
    this.outcomes = new OutcomeRepository(store); this.pet = new PetRepository(store);
  }
  usage(state: TurnState, sequence: number, input: unknown): void {
    const value = ObservedUsageSchema.parse(input), cached = value.cacheReadTokens + value.cacheWriteTokens;
    if (!Number.isSafeInteger(cached) || !Number.isSafeInteger(value.inputTokens + cached)) throw Error('用量溢出');
    this.store.run('INSERT OR IGNORE INTO model_usage VALUES(?,?,?,?,?,?,?)', state.turn_id, sequence, state.session_id,
      value.inputTokens + cached, value.outputTokens, cached, localTimestamp());
  }
  recordSkillUse(state: TurnState, skillId: string): void { this.store.run('INSERT OR IGNORE INTO skill_use VALUES(?,?)', state.task_id, skillId); }
  finish(state: TurnState, fault?: () => void): { progress: PetProgressEvent; events: ServiceEvent[] } {
    if (['queued', 'running'].includes(state.status)) throw Error('任务尚未结束');
    return this.store.transaction(() => {
      const prior = this.store.connection.prepare('SELECT progress_json FROM turn_settlement WHERE task_id=?').get(state.task_id);
      if (prior) return { progress: PetProgressEventSchema.parse(parseStoredJson(String(prior.progress_json))), events: [] };
      this.turns.save(state); this.turns.saveReply(state);
      let pet = this.pet.get() ?? PetStateSchema.parse({});
      let progress = PetProgressEventSchema.parse({ current_exp: pet.exp, required_exp: requiredExp(pet.level) });
      const task = difficulty(state.input_text), now = localTimestamp();
      const status = state.status === 'completed' ? 'success' : state.status === 'interrupted' ? 'cancelled' : state.status;
      const existed = this.store.connection.prepare('SELECT id FROM task_record WHERE id=?').get(state.task_id);
      this.store.run(`INSERT OR IGNORE INTO task_record(id,input_text,task_type,status,difficulty,reward_exp,created_at,finished_at)
        VALUES(?,?,'general',?,?,?,?,?)`, state.task_id, state.input_text, status, task.difficulty, task.reward, now, now);
      this.store.run('INSERT OR IGNORE INTO task_result(task_id,success,raw_result,summary,error_message,created_at) VALUES(?,?,?,?,?,?)',
        state.task_id, Number(state.status === 'completed'), state.output_text, state.output_text, state.error, now);
      if (state.status === 'completed' && !existed) {
        ({ pet, progress } = rewardCompletion(pet, state.input_text));
        const count = Number(this.store.connection.prepare("SELECT count(*) n FROM task_record WHERE status='success'").get()!.n);
        for (const ability of availableAbilities(pet, count)) if (this.store.run('INSERT OR IGNORE INTO unlocked_abilities VALUES(?,?)', ability.id, now).changes) {
          progress.unlocked_abilities.push([ability.id, ability.name]);
        }
      }
      this.pet.save(pet);
      const outcome = this.outcomes.finishTurn(state.turn_id, state.status);
      this.store.run('INSERT INTO turn_settlement VALUES(?,?,?,?,?)', state.task_id, state.turn_id, state.status, JSON.stringify(progress), now);
      // Ordinary dialogue can retain historical EXP but never counts as verified skill success.
      const events = [this.turns.event(state, 'task.outcome', { ...outcome }),
        this.turns.event(state, 'progress.changed', { ...progress }),
        this.turns.event(state, `turn.${state.status}`, { status: state.status, error: state.error })];
      fault?.(); return { progress, events };
    });
  }
  recover(): void {
    this.turns.interruptUnfinished();
    const missing = this.store.connection.prepare(`SELECT t.turn_id FROM service_turn t LEFT JOIN turn_settlement s ON s.turn_id=t.turn_id WHERE s.turn_id IS NULL`).all();
    for (const row of missing) this.finish(this.turns.get(String(row.turn_id)));
  }
  summary() {
    const usage = this.store.connection.prepare(`SELECT COALESCE(SUM(input_tokens),0) AS input, COALESCE(SUM(output_tokens),0) AS output,
      COALESCE(SUM(cached_tokens),0) AS cached,COUNT(*) AS calls FROM model_usage`).get();
    const completed = this.store.connection.prepare("SELECT count(*) n FROM task_record WHERE status='success'").get()!.n;
    const unlocked = new Map(this.store.connection.prepare('SELECT * FROM unlocked_abilities').all().map(row => [row.ability_id, row.unlocked_at]));
    return ProgressOverviewSchema.parse({ completed_tasks: completed, usage, pet: this.pet.getOrCreate(),
      abilities: ABILITIES.map(ability => ({ ...ability, unlocked_at: unlocked.get(ability.id) ?? null })) });
  }
}
