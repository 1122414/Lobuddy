import { PetStateSchema, PetPersonalitySchema, type PetState } from '@lobuddy/contracts';
import { Store } from './database.js';
export class PetRepository {
  constructor(private readonly store: Store) {}
  get(id = 'default'): PetState | undefined {
    const row = this.store.connection.prepare('SELECT * FROM pet_state WHERE id=?').get(id);
    if (!row) return undefined;
    let personality = PetPersonalitySchema.parse({});
    try {
      personality = PetPersonalitySchema.parse(row.personality_json ? JSON.parse(String(row.personality_json)) : {});
    } catch { /* Preserve legacy fallback without exposing malformed private content in logs. */ }
    return PetStateSchema.parse({ ...row, personality });
  }
  save(value: PetState): void {
    const pet = PetStateSchema.parse(value);
    this.store.run(`INSERT INTO pet_state(id,name,level,exp,evolution_stage,mood,skin,personality_json,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,level=excluded.level,exp=excluded.exp,
      evolution_stage=excluded.evolution_stage,mood=excluded.mood,skin=excluded.skin,personality_json=excluded.personality_json,updated_at=excluded.updated_at`,
      pet.id, pet.name, pet.level, pet.exp, pet.evolution_stage, pet.mood, pet.skin, JSON.stringify(pet.personality), pet.created_at, pet.updated_at);
  }
  getOrCreate(id = 'default'): PetState {
    const current = this.get(id); if (current) return current;
    const value = PetStateSchema.parse({ id }); this.save(value); return value;
  }
}
