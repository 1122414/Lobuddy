import { localTimestamp } from '@lobuddy/contracts';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
export class Preferences {
  constructor(private readonly store: Store) {}
  get(key: string): string | undefined {
    const value = this.store.connection.prepare('SELECT value FROM app_settings WHERE key=?').get(key)?.value;
    return value === undefined ? undefined : String(value);
  }
  json(key: string): unknown { const value = this.get(key); return value === undefined ? {} : parseStoredJson(value); }
  set(key: string, value: string): void {
    this.store.run(`INSERT INTO app_settings VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET
      value=excluded.value,updated_at=excluded.updated_at`, key,value,localTimestamp());
  }
}
