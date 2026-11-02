import { Temporal } from '@js-temporal/polyfill';

export function careMessageTime(value: string, timezone: string): number {
  return /(?:Z|[+-]\d\d:\d\d)$/u.test(value) ? Temporal.Instant.from(value).epochMilliseconds / 1000 :
    Temporal.PlainDateTime.from(value).toZonedDateTime(timezone,{ disambiguation: 'earlier' }).epochMilliseconds / 1000;
}
/** Time is resolved from the source message, never from a model's invented timestamp. */
export function careNextAt(text: string, at: number, timezone: string): number {
  const base = Temporal.Instant.fromEpochMilliseconds(Math.trunc(at * 1000)).toZonedDateTimeISO(timezone);
  let day: Temporal.PlainDate | undefined;
  const absolute = /(\d{4})[-年](\d{1,2})[-月](\d{1,2})(?:日)?/u.exec(text);
  const relative = /今天|明天|后天/u.exec(text);
  const weekly = /(本周|这周|下周)(?:星期|周)?([一二三四五六日天])/u.exec(text);
  try {
    if (absolute) day = Temporal.PlainDate.from({ year: Number(absolute[1]),month: Number(absolute[2]),day: Number(absolute[3]) },{ overflow: 'reject' });
    else if (weekly) day = base.toPlainDate().subtract({ days: base.dayOfWeek - 1 }).add({ days: '一二三四五六日'.indexOf(weekly[2]!.replace('天','日')) + (weekly[1] === '下周' ? 7 : 0) });
    else if (relative) day = base.toPlainDate().add({ days: relative[0] === '后天' ? 2 : relative[0] === '明天' ? 1 : 0 });
    if (!day) return at + 48 * 3600;
    // Unknown event duration is not guessed. Explicit follow-up instructions may name the requested time.
    const follow = /再(?:问|聊|提)|问我|找我聊/u.test(text);
    const clock = /(?:(上午|早上|下午|晚上|中午)\s*)?(\d{1,2})(?::(\d{2})|点(?:(\d{1,2})分)?)?/u.exec(text.replace(absolute?.[0] ?? weekly?.[0] ?? relative?.[0] ?? '', ''));
    let hour = 10, minute = 0;
    if (follow && clock) {
      hour = Number(clock[2]); minute = Number(clock[3] ?? clock[4] ?? 0);
      if (['下午','晚上'].includes(clock[1] ?? '') && hour < 12) hour += 12;
    } else if (!follow) day = day.add({ days: 1 });
    const wall = day.toPlainDateTime({ hour,minute });
    const zoned = wall.toZonedDateTime(timezone,{ disambiguation: 'earlier' });
    if (!zoned.toPlainDateTime().equals(wall)) return at + 48 * 3600;
    const next = zoned.epochMilliseconds / 1000;
    return next > at && next <= at + 90 * 86400 ? next : at + 48 * 3600;
  } catch { return at + 48 * 3600; }
}
export function careWindow(now: number, timezone: string, start: number, end: number): boolean {
  const hour = Temporal.Instant.fromEpochMilliseconds(Math.trunc(now * 1000)).toZonedDateTimeISO(timezone).hour;
  return hour >= start && hour < end;
}
