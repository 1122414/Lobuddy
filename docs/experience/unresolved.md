# Unresolved observations

## P8 / 2026-10-19: incomplete historical stop evidence

`reports/2026-10-19_n6_voice_soak.json` stopped after its 120-second sample without retaining a UI error. `reports/2026-10-19_n6_voice_soak_fixed.json` stopped after its 1474-second sample with state off and no error, but without native window events. These historical runs do not independently establish a cause; do not assign one from later similar symptoms.

Subsequent distinct findings are now recorded in [capture lifecycle ownership](patterns/async-lifecycle-ownership.md) (bounded capture overflow, fixed and fault-tested) and [multiwindow ownership](patterns/multiwindow-ownership.md) (window hide stops voice as intended, confirmed by native events and user feedback). The complete post-fix resource rerun remains the next verification step. Physical voice quality remains a separate human acceptance item.


The quiet short test passed, but `reports/2026-10-19_n6_voice_soak_isolated.json` again recorded native quick-window hide followed by the main stop event before the full-duration test could continue. The user confirmed earlier manual hiding, but the exact trigger of each later hide was not observed. Stop blind relaunches on this desktop; use an uninterrupted test environment for the full-duration gate. Do not bypass the product's hide/close microphone-release handler. No voice soak is marked passed.

## T4 / 2026-10-21: synthetic vision discrepancy

The first native TS model probe completed a 128px solid-red image request in an existing tool conversation, but its reply failed the red-colour assertion. The response was not retained, so the cause is unknown. A subsequent independent-session 400x200 red-square/blue-circle image matched the existing Python acceptance fixture and passed all four colour/shape assertions. These changed both image content and conversation context; they do not establish a fix for the earlier observation. Next check: run a fixed cross-product of both images with fresh/existing sessions, retaining only sanitized synthetic outputs. See `qualification/ts-runtime/task-probe.cts` and the T4 report. No general image-quality guarantee is inferred.

## Product scan / 2026-10-28: natural phrasing misses durable dialogue control

Facts, verified once at `6168928` in isolated synthetic SQLite data: real `CompanionDialogue.respond()` sets `listening` for `先听我讲`, but `discussing` for `我今天有点累，先听我讲就好`. With independent sessions and cleared boundaries, `今天不聊工作` sets `quiet` and blocks project topics, while `今天不想聊工作` leaves `discussing` and no boundary. The narrow regular expressions in `packages/service/src/companion/dialogue.ts` explain these state differences. See `reports/2026-10-28_product_state_and_evolution.md` (LS-03).

This does not measure the model's immediate answer: it may understand the current message without a persisted control state. The untested product concern is whether later proactive behavior violates the intended boundary. No repair was applied. Next checks: equivalent natural phrasings, quote/hypothetical/negation counterexamples, source-backed topic selection after the boundary, and expiration behavior. Keep automatic state changes conservative rather than treating all mentions as instructions.

## T7 / 2026-10-21: first native workflow proposal failed without phase evidence

The first TS native evolution run produced a verified task trace, then its `workflow_proposal` job failed once before a candidate was persisted. Only the generic learning error was retained; the model/provider response was deliberately not logged. A later run with fixed failure categories completed the real proposal, forty-case evaluation, activation, subsequent-task improvement, rollback and no-improvement rejection. No category fired on that passing run, so the original cause remains unknown. Do not attribute it to truncation, JSON fences, credentials or the added error classifier without evidence. If it recurs, retain only the fixed `WorkflowProposalError` category and job phase; keep provider content and credentials excluded. Stable workflows remain active after failed proposals.
