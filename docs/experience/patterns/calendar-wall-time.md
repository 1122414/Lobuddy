# Preserve a reminder's calendar zone when editing

Signals: an existing periodic reminder changes its timezone after editing only its title; behavior diverges after DST even when the first UTC instant stays the same.

Mechanism: formatting and parsing a `datetime-local` input with the machine timezone discards the stored calendar zone. A daily 09:00 New York reminder edited on a Shanghai machine became a daily 21:00 Shanghai rule. These agree initially but diverge after a DST transition.

Handling: display existing values with their stored IANA zone. Resolve wall time in Python through a strict read-only protocol operation using `ZoneInfo`; reject nonexistent times by round-trip validation and choose the first fold for ambiguous times, consistent with the scheduler. Preserve the reminder zone while editing and show it explicitly. Keep protocol retention transient for this pure conversion.

Verified once on 2026-10-19: `TestCalendarRules.test_wall_time_uses_stored_zone_not_machine_zone`, gap/invalid/fold cases, and `desktop/tests/scheduling-smoke.cjs`. The native pre-fix assertion observed `Asia/Shanghai` replacing `America/New_York`; post-fix retained zone, first instant and 09:00 recurrence, while updating the title. This does not provide a global application timezone setting or change existing schedules when the system timezone changes.
