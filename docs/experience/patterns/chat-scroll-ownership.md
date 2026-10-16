# Preserve reading position across conversation refreshes

Signals: a user scrolls upward, then new tokens or an unchanged task refresh jumps the conversation to the bottom.

Mechanism: an effect keyed by a task array runs when polling creates a new array, even if the task content is unchanged. Unconditional `scrollIntoView` overrides the user's reading position and may scroll ancestor containers too.

Handling: retain whether the actual scroll container was at its bottom before content updates. Update that intent from scroll events; upward wheel input disables following immediately. Only set that container's scrollTop when following. Reset following on an explicit session change, not on task-array identity. Use a small pixel tolerance for fractional scroll positions.

Verified once, 2026-10-16: `desktop/tests/conversation-scroll.cjs` renders the production component in Chromium with deterministic history, streamed task updates and completed messages. It verifies stable scrollTop while reading, resumed following at bottom and session-switch reset. The test makes no model calls and does not use real conversation data. This does not establish reading-anchor preservation if messages above the viewport are edited or removed.
