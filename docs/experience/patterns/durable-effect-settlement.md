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


E5 integration added a conservative composition rule: independent scenario results in one turn must retain earlier unknown or failed goals. A successful digest cannot overwrite a file-copy preview that has not executed. `TestEvolutionIntegration.test_later_different_scenario_cannot_hide_unknown_goal` verifies this case; it does not infer whether the user abandoned a previous subgoal.

## Completion events belong to the settlement transaction

N6 found two missing-event paths: reminder delivery never emitted `delegation_completed`, and task completion emitted it only in a later service callback. A process loss after settlement could leave dependent delegations waiting forever. Persist the unique run completion event in the same transaction as the verified result; unknown, failed, cancelled or stale-revision results must not publish it. Resume the next periodic cursor from durable completed state during scheduler reconciliation, rather than relying on a one-time callback. Never replay the completed run.

Verified once on 2026-10-19: `TestPersistentScheduling.test_reminder_completion_triggers_dependent_once_after_restart`, `test_periodic_task_resumes_after_settlement_crash_only_when_verified`, and `TestDelegationRun.test_execution_completion_is_not_goal_success` plus its stale-result case. Pre-fix reminder chain produced zero dependent notifications; post-fix produces one despite repeated ticks/restart. This covers delegation completion signals, not arbitrary external side effects or every notification callback.

## TypeScript delegation recovery

T6 moves delegation outcome and notification creation into `RuntimeLedger.finish` alongside the reply, reward and terminal event. `delegation-execution.test.ts` injects a failure immediately before commit and verifies there is no partial completion. Resuming a verified local readonly checkpoint keeps its original task/turn/run identity and durable tool/time budget. An interrupted settlement can be revised to completed once; an already completed settlement cannot award again. Inbox text is revised under the same identity and any prior Jev judgment becomes stale, without another automatic provider call. Unknown file writes are inspected by source/target SHA-256 and never replayed.

Verified once on 2026-10-21 with seven application-chain tests, an independent 94-test integration snapshot, and native utility restart. This does not provide readonly recovery for mutable remote URLs or reverse external side effects.
