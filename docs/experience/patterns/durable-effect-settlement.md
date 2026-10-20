# Settle completed work exactly once, independently of transport

## Signals and mechanism

An event stream can reconnect or repeat, while a renderer can reload after the result was saved. Updating EXP or skill counters in a UI callback multiplies side effects. A crash between saving the reply and awarding progress leaves a different gap: a successful task with no settlement.

## Handling

Use a transaction containing the settlement marker, pet mutation, ability unlocks and skill statistics. The marker is unique by task and turn. Persist the terminal reply first; on startup settle terminal records without a marker, never enqueue their agent work again. Preserve legacy task IDs and skip rewards already represented by legacy completed task records. Failed/cancelled/interrupted turns do not earn success rewards; cancellation does not count as a skill failure.

Count observed usage by (turn ID, engine event sequence). In DSH 0.1.5rc1, `inputTokens` excludes `cacheReadTokens` and `cacheWriteTokens`; the displayed input total is their sum, and cached tokens are a subset of that total. Reasoning tokens are a subset of output, not an additional charge. Missing usage is not zero-cost evidence.

## Evidence and limits

Verified once on 2026-10-16: `tests/test_runtime_ledger.py` covers duplicate settlement, restart, cached-token totals and transactional rollback. `scripts/smoke_dsh_images.py` verifies real DSH usage and duplicate submission without repeated rewards. See `reports/2026-10-16_p5_capabilities.md`. This does not guarantee external side effects can be rolled back; never replay a possibly completed tool action automatically.

## Execution completion is not goal verification

Verified once in E3 (`tests/test_practical_tasks.py`, updated `test_runtime_ledger.py`): a completed model turn and a skill-read event do not prove success. Keep `task_acceptance` separate, with explicit criteria and independently obtained evidence. Retain historical EXP semantics as interaction history, but never increment skill success merely for reading its instructions. New controlled copy operations persist a started marker before filesystem effects; an unknown marker rejects replay, including a fresh call ID in the same turn. Recovery cannot promise to undo external effects. Coverage and verbatim source checks validate an extractive brief only, not semantic completeness.
