# Unresolved observations

## P8 / 2026-10-19: incomplete historical stop evidence

`reports/2026-10-19_n6_voice_soak.json` stopped after its 120-second sample without retaining a UI error. `reports/2026-10-19_n6_voice_soak_fixed.json` stopped after its 1474-second sample with state off and no error, but without native window events. These historical runs do not independently establish a cause; do not assign one from later similar symptoms.

Subsequent distinct findings are now recorded in [capture lifecycle ownership](patterns/async-lifecycle-ownership.md) (bounded capture overflow, fixed and fault-tested) and [multiwindow ownership](patterns/multiwindow-ownership.md) (window hide stops voice as intended, confirmed by native events and user feedback). The complete post-fix resource rerun remains the next verification step. Physical voice quality remains a separate human acceptance item.


The quiet short test passed, but `reports/2026-10-19_n6_voice_soak_isolated.json` again recorded native quick-window hide followed by the main stop event before the full-duration test could continue. The user confirmed earlier manual hiding, but the exact trigger of each later hide was not observed. Stop blind relaunches on this desktop; use an uninterrupted test environment for the full-duration gate. Do not bypass the product's hide/close microphone-release handler. No voice soak is marked passed.

## T4 / 2026-10-21: synthetic vision discrepancy

The first native TS model probe completed a 128px solid-red image request in an existing tool conversation, but its reply failed the red-colour assertion. The response was not retained, so the cause is unknown. A subsequent independent-session 400x200 red-square/blue-circle image matched the existing Python acceptance fixture and passed all four colour/shape assertions. These changed both image content and conversation context; they do not establish a fix for the earlier observation. Next check: run a fixed cross-product of both images with fresh/existing sessions, retaining only sanitized synthetic outputs. See `qualification/ts-runtime/task-probe.cts` and the T4 report. No general image-quality guarantee is inferred.

## Product scan / 2026-10-28: dialogue experience quality remains unmeasured

The confirmed narrow-phrasing state defect was repaired in A1 and moved to [explicit dialogue intent](patterns/explicit-dialogue-intent.md), with current unit and native UI evidence. A2 repaired proactive handoff and B adds bounded source selection and free expression; see [proactive continuity](patterns/proactive-conversation-continuity.md) and the stage reports for narrow real-model evidence. Remaining product checks include real-model listening quality, unsupported/ambiguous natural instructions and sustained naturalness. State correctness is not a measurement of empathy or naturalness.

## Desktop activation / 2026-10-28: automated foreground return was not established

Facts: during B's isolated native test, show/focus and explicit app activation did not make the management BrowserWindow report `isFocused() === true` within the bounded check. No new return event was recorded after the old pending event had been cleared. A separate pending-event fixture generated an actual reviewed bubble through the real service and model. `desktop/electron/windows.ts` still sets management windows focusable and connects native focus to the trusted trigger.

The cause of the activation failure is unverified; an automation/session environment condition is a hypothesis, not a diagnosed product defect. Do not keep relaunching the same focus experiment or describe the offline event fixture as proof of native OS activation. F's next check is an actual foreground return on the target desktop, recording focus/visibility and the trusted event before testing the eventual bubble. Preserve the renderer's prohibition on directly triggering this event. Physical voice and interruption behavior remain separate gates.

## B2 / 2026-10-28: safe selection does not yet produce stable initiative

Facts: the original contextual comparison matched 15/16 expectations, followed by `pass/low_value` for two expected-positive project plans. Later bounded two-draft selection and clause-based review improved initiative but did not establish stable factuality. `reports/2026-10-30_b2_separated_full.json` matched 25/28: a bookmark positive had an invalid extra review field; the pinecone primary lacked the required four-codepoint shared fragment and its alternate was rejected; a direct project-intention review incorrectly approved turning a project plan into the user's wish. Manual reading also retains an unsupported ongoing-action presupposition in the map example. These are observed distinct failures, not one proven prompt cause.

The short-followup native test subsequently produced 1/1/2 sentences with single paragraphs (`reports/2026-10-28_b2_native_short_followups.json`). A later native invitation passed with an earlier prompt version; it does not validate the newest channel/visual-boundary changes. Low-reasoning review experiments failed through output truncation and wrong judgments; those runtime/budget changes were reverted. Full engineering checks passing is separate from these model-quality failures.

Next: resolve these supported format/quote/actor boundaries, then compare retained positives, stale/configuration negatives and held-out topics with unchanged expectations. Keep factuality, willingness to speak and naturalness separate; retain every failed run and do not redefine positives as optional silence just to pass. B1 is complete; B2 quality and the overall product goal remain open. C1's public-cache work can be independently validated but does not close this gap.

2026-11-02 S1: six early targeted real-model cases matched expectations, but the remaining `unfinished-shared-context` positive still returned pass: the reviewer classified a mixed statement/open question as fact with null evidence and did not select the alternate. This observed failure does not establish one general prompt cause. Later prompt/source-time changes still need a complete fixed-version comparison. The shared evaluation ledger reached 19 calls / 63,479 reserved input / 19,456 reserved output, leaving less than one 1,024-output reservation. Later no-call pass results are not model evidence. Preserve the ledger and resume after the calendar allowance renews; see `reports/2026-11-02_s1_quality_progress.md`.

## S3 / 2026-11-02: automatic real-model care remains unverified

Facts: fixed-clock state/visibility/failure tests and zero-model native prepared-utterance delivery passed, including restart and forgetting. The real-model native branch stopped at shared-budget preflight before launch. It has not verified automatic ordinary-update extraction, current invitation quality or short-response naturalness. Next: after S1 and budget availability, run `LOBUDDY_CARE_REAL_MODEL=1` with the existing native fixture and a new report, retaining every failed attempt and the common ledger. See `reports/2026-11-02_s3_delivery_progress.md`. Seven-day human observation has not begun.

## S4 / 2026-11-02: anonymous public release gate remains unavailable

Facts: the native product path returned unavailable for all three configured public sources. A separate public header diagnostic returned HTTP403, anonymous limit60/remaining0. One native retry after the announced reset again failed at public-read; the subsequent response dated08:13:42 UTC still reported remaining0 and a new reset. No authenticated connector or fixture was substituted. Individual native failures did not retain raw HTTP responses, so the header diagnostic does not prove each request's failure reason. Cache, restart, disable and full memory comparison in that native sequence were not reached. Keep S4 and dependent S5 open; retry once conditions change, preserving local read limits and failure backoff. See `reports/2026-11-02_s4_network_gate.json`.

## T7 / 2026-10-21: first native workflow proposal failed without phase evidence

The first TS native evolution run produced a verified task trace, then its `workflow_proposal` job failed once before a candidate was persisted. Only the generic learning error was retained; the model/provider response was deliberately not logged. A later run with fixed failure categories completed the real proposal, forty-case evaluation, activation, subsequent-task improvement, rollback and no-improvement rejection. No category fired on that passing run, so the original cause remains unknown. Do not attribute it to truncation, JSON fences, credentials or the added error classifier without evidence. If it recurs, retain only the fixed `WorkflowProposalError` category and job phase; keep provider content and credentials excluded. Stable workflows remain active after failed proposals.
