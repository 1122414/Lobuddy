import { JsonValueSchema } from '@lobuddy/contracts';
import { StorageError } from './database.js';

/** Reject precision loss before persisted JSON is accepted by a domain schema. */
export function parseStoredJson(text: string): unknown {
  const value: unknown = JSON.parse(text, (_key: string, item: unknown) => {
    if (typeof item === 'number' && (!Number.isFinite(item) || (Number.isInteger(item) && !Number.isSafeInteger(item)))) {
      throw new StorageError('持久化 JSON 包含无法安全表示的数值');
    }
    return item;
  });
  return JsonValueSchema.parse(value);
}
