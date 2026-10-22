# Preserve authority while changing working methods

## Signals and mechanism

A model-generated workflow can look simpler while losing source fields or expanding tool access. Model approval is not independent validation. Execution completion also cannot settle unknown filesystem writes.

## Handling and limits

Use immutable declarations with a fixed evaluator outside candidate data. Separate parameter proposals from executable Python/JavaScript. In the first Lobuddy implementation, only lossless context serialization is automatically promotable: all held-out cases preserve parsed data, permissions stay fixed, and UTF-8 bytes improve without regression. This proves serialization properties, not semantic answer quality. Other changes remain review proposals. Pin a version per run; use a five-run probation, explicit rollback, and crash recovery without tool replay. Keep application source, evaluation fixtures and private data outside governed tool access even if the user selects the project root as workspace.

## Evidence

Verified once (2026-10-16): `tests/test_workflows.py`, `tests/test_workflow_service.py`, `desktop/tests/workflows-smoke.cjs`, `scripts/smoke_evolution.py`. The first full-definition model generation received a generic bridge rejection; its underlying cause was not established. A smaller typed format/reason proposal passed real validation without increasing output budgets. Do not generalize that all bridge rejections are output-length failures.

## 10.19 task-method extension

The original limit above describes E4, not the current expanded evaluator. N5 permits one additional method: reuse an unchanged local source within one digest task, while preserving every original source reference. Links are never cached. A candidate must consume an actual verified task trace with duplicate canonical-source references; a detached source ID or model assertion is insufficient. Compare identical synthetic inputs and actual governed workflow execution, preserve source/evidence/quoted output, and gate on physical reads instead of noisy wall-clock time. Model semantic scoring remains insufficient.

Verified once: `tests/test_method_learning.py`, `core/service/digest_evaluation.py`, `scripts/smoke_method_learning.py`; real model proposed a trace-backed change, 40 fixed task comparisons reduced reads 110→75, the next task reduced 3→2 with S1/S2/S3 preserved, rollback restored 3, and no-improvement candidate was rejected. The E5 ledger appends an artifact evidence record, so assertions must compare source refs rather than assume every evidence item is a source.

A fixed error classifier established that this run's 1024-token auxiliary call was truncated. Method proposals now reserve and request 2048 output tokens, keeping the daily cap and rejecting incomplete output. Generic prior bridge failures remain unknown; do not infer truncation from a generic error. Diagnostic classifications must never expose arbitrary provider messages or credentials.

## TypeScript migration and idle ownership (2026-10-21)

The TS evaluator uses the actual governed digest executor in an isolated temporary workspace. Forty fixed comparisons preserve source refs, quotes and changed-source behavior while reducing reads 110→75; model generation sees only a development example or sanitized real trace, never holdout answers. Promotion requires the current parent, immutable candidate body, fixed evaluator and unchanged source authority. Observation is unique per run; a cancelled run does not count as a verified success, and an interrupted probation can revert without replaying effects.

Management polling must not reset the idle timer. The initial TS companion wrapper preempted learning for all `project.*` and `source.*` calls, including periodic read-only panels; adding skill/workflow polling exposed the same causal issue. Preempt only explicit mutations and actual foreground activity. `application.test.ts` keeps polling all four management lists while proving the skill evidence job completes after the configured idle interval. Verified once, not a claim that all possible UI polling interactions were audited.

Generated skills use the same trigger/content validator as manual edits. Source-backed Chinese candidate text now includes the required `When to use` section, and candidate table status overrides stale serialized metadata. `skills.test.ts` verifies approval, replay, versions, disable/restore, source forgetting and projection recovery. See the T7 report and native evidence; the first unclassified model-proposal failure remains in `unresolved.md`.

## Authority and result feedback, 2026-10-22

Rollback changes the selected version, not the user's enable/disable decision. A failed probation or restart recovery formerly wrote `enabled=1`, resurrecting a disabled workflow. Four enabled/disabled × failure/recovery regressions in `workflows.test.ts` preserve the flag and cover explicit later enable. This defect was observed before repair.

Persist comparison outcome and activation in one transaction. When the parent changed or was disabled, the previous implementation saved `review/promote` before throwing, leaving a record that the UI could neither reevaluate nor activate. `workflow-promotion.test.ts` now checks explicit rejection with retained comparison metrics and an activation SQL fault that leaves the candidate untouched for retry. Do not silently rebase the candidate or interpret a successful comparison as successful activation.

An already-improved workflow can legitimately return no proposal without invoking the model. Charging its full reservation repeatedly starves useful work. `rsi-learning.test.ts` exercises the actual generator and a one-call daily budget. Only a completed attempt that never invoked `analyze()` refunds its untouched reservation, against the original reservation date and attempt CAS, atomically with completion. Failed/interrupted/unknown requests keep their reservation; these tests do not justify refunding estimated token differences. Midnight, late attempts and transaction failures are covered in `learning.test.ts`. Verified once with synthetic domain/service executions; see `reports/2026-10-22_rsi_feedback.md` for stage validation.
