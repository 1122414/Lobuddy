import { Temporal } from '@js-temporal/polyfill';
import { RepeatRuleSchema, ScheduleResolveSchema, type RepeatRule } from '@lobuddy/contracts';

export function resolveWallTime(local: string, timezone: string): number {
  const input = ScheduleResolveSchema.parse({ local,timezone });
  const wall = Temporal.PlainDateTime.from(input.local);
  const instant = wall.toZonedDateTime(input.timezone,{ disambiguation: 'earlier' });
  if (!instant.toPlainDateTime().equals(wall)) throw Error('该当地时刻不存在，请重新选择时间');
  return instant.epochMilliseconds / 1000;
}
export function nextOccurrence(input: RepeatRule, timezone: string, after: number): number | null {
  const rule = RepeatRuleSchema.parse(input); if (rule.frequency === 'once') return null;
  const initial = Temporal.Instant.fromEpochMilliseconds(Math.trunc(after * 1000)).toZonedDateTimeISO(timezone).toPlainDate();
  for (let offset = 0; offset < 370; offset++) {
    const day = initial.add({ days: offset });
    if (rule.frequency === 'weekly' && !rule.weekdays.includes(day.dayOfWeek - 1)) continue;
    const wall = day.toPlainDateTime(Temporal.PlainTime.from(rule.local_time));
    const candidate = wall.toZonedDateTime(timezone,{ disambiguation: 'earlier' });
    if (!candidate.toPlainDateTime().equals(wall)) continue;
    const instant = candidate.epochMilliseconds / 1000;
    if (instant > after) return rule.end_at === null || instant <= rule.end_at ? instant : null;
  }
  return null;
}
