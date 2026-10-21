import { z } from 'zod';
import { Temporal } from '@js-temporal/polyfill';

export function unicodeString(limits: { min?: number; max?: number; pattern?: string } = {}) {
  const pattern = limits.pattern === undefined ? undefined : new RegExp(limits.pattern, 'u');
  return z.string().superRefine((value, context) => {
    const count = [...value].length;
    if ((limits.min !== undefined && count < limits.min) ||
        (limits.max !== undefined && count > limits.max) || (pattern && !pattern.test(value))) {
      context.addIssue({ code: 'custom', message: 'String violates its declared contract' });
    }
  });
}

// Match Python str.strip: BOM is not whitespace, U+0085 and U+001C–1F are.
export function trimUserText(value: string): string {
  return value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, '');
}

export function dateTimeString() {
  return z.string().refine(value => {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value) || value.startsWith('0000')) return false;
    try {
      if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(value)) Temporal.Instant.from(value);
      else Temporal.PlainDateTime.from(value);
      return true;
    } catch { return false; }
  }, 'Invalid serialized timestamp');
}

export function localTimestamp(): string {
  const now = new Date();
  return Temporal.PlainDateTime.from({ year: now.getFullYear(), month: now.getMonth() + 1,
    day: now.getDate(), hour: now.getHours(), minute: now.getMinutes(), second: now.getSeconds(),
    millisecond: now.getMilliseconds() }).toString({ fractionalSecondDigits: 6 });
}
