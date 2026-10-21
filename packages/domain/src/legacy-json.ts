/** Preserve Pydantic float spellings in persisted request/schedule identities. */
export function legacyFloat(value: number): string {
  if (!Number.isFinite(value)) throw Error('Non-finite legacy number');
  if (Object.is(value,-0)) return '-0.0';
  if (value !== 0 && (Math.abs(value) >= 1e16 || Math.abs(value) <= 1e-6)) return value.toExponential();
  return Number.isInteger(value) ? `${value}.0` : String(value);
}
export function delegationJson(value: unknown): string {
  const serialize = (item: unknown, key = ''): string => {
    if (typeof item === 'number' && ['at','end_at','expires_at'].includes(key)) return legacyFloat(item);
    if (Array.isArray(item)) return '[' + item.map(value => serialize(value)).join(',') + ']';
    if (item !== null && typeof item === 'object') return '{' + Object.entries(item).map(([name,value]) => JSON.stringify(name) + ':' + serialize(value,name)).join(',') + '}';
    const result = JSON.stringify(item); if (result === undefined) throw Error('Invalid legacy value'); return result;
  };
  return serialize(value);
}
