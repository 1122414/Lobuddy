# Typed advisory decisions: independent evidence and durable attempts

## Signals and mechanism

A decision model may correctly label an urgent notification while reporting uncertainty below the application's threshold. Also, demanding high confidence for every independent question can let irrelevant urgency uncertainty defeat a confident irrelevance veto.

Neither model-selected labels nor reported confidence authorize side effects. A notification poll is repeated and can arrive from multiple windows; making an unrecorded API call from each poll multiplies spend and replays interrupted requests.

## Handling

- Ask atomic, observable questions. In this integration, replace hypothetical loss-of-value reasoning with explicit deadline/immediate-action detection.
- Keep a fixed confidence floor. Apply a confident duplicate/irrelevance veto first; require all necessary positive evidence for immediate notification. Uncertainty falls back conservatively.
- Validate option keys, finite probabilities, normalized distribution, winning choice and the documented confidence formula (with rounding tolerance). Retain model version and actual usage separately.
- Reserve attempts and local budgets before network I/O; use notification identity, one async owner and a generation check. After awaiting, recheck quiet state, current notification and source context.
- Keep decision evidence free of copied source text. Source cancellation/forgetting must still invalidate delivery through existing authoritative rules.
- Observational decisions must never become active retroactively. Provider errors expose fixed safe codes, not response bodies, authorization headers or request content.
- When adding an independent provider, check credential loading on a clean commit snapshot: an explicit primary-model key must not suppress the provider's Keychain entry. Child-process tests must provide synthetic credentials for every provider to avoid depending on the developer's OS store. This dependency was exposed by the isolated Jev commit tests, not by the dirty-tree suite.

## Evidence and limits

Verified once on 2026-10-20 in `tests/test_jev.py`, native `desktop/tests/jev-smoke.cjs` and `scripts/smoke_jev.py`.
First six-case real run scored 5/6: explicit five-minute deadline had urgency confidence 0.69, below 0.75. Narrower timing wording fixed that case; the second run exposed the independent-veto composition defect. The corrected implementation preserved thresholds and passed the original six and four additional cases.

Reports `reports/2026-10-20_jev_real_acceptance*.json` preserve both failures and the final run; `reports/2026-10-20_jev_holdout.json` contains the additional cases. This is a small functional acceptance set, not evidence of general accuracy, latency superiority, universal injection resistance or safe authority delegation. Jev remains advisory and cannot modify permission or promotion rules.

## Bounded companion selection and review (2026-10-28)

A service reservation is not an engine request limit. The pinned DSH analysis bridge accepts at most 7000 UTF-8 prompt bytes, while a two-call job may reserve 16384 input units. Bound each prompt at the actual bridge before invoking it, then retain the shared job/day reservation. A job that already owns its reservation must remain eligible to finish even when the remaining day balance is zero.

The pinned rc.1 DeepSeek adapter defaults to high reasoning. Real small JSON tasks repeatedly finished with `analysis_truncated` at 1024 outputs, and some also at 2048. The visible answer length did not explain the failure. Diagnose with fixed bridge classifications, not raw provider failures. The bridge now accepts an explicit `reasoningEffort: off` only for callers that request it; companion selection and review use it, while other analysis and foreground calls retain their prior defaults. Tools/history remain empty, truncation remains a rejection, and permissions/evaluators are unchanged. Four real review counterexamples rejected invented completion, false personal experience, pressure and invented emotion in short mode; a subjective metaphor was accepted. This is limited evidence, not general accuracy.

Use speak/defer/pass as actual terminal decisions. No source, failed generation or unavailable review produces silence without consuming display quota. Preserve current source revision, relationship epoch, activity generation and process ownership after every await and before display. A deferred old conversation event must carry elapsed time; its name alone must not imply the conversation just ended. Tell the model about deterministic delivery delays that the system already enforces.

Normal completion may return only provably unused call allocations, bounded by the remaining reservation. Settle atomically with the exact job attempt and original reservation day; stale/repeated settlement must not refund again. This opt-in is used only for companion jobs. Already invoked calls retain their conservative allocations; failed/interrupted jobs retain their reservations. Default-budget defer/re-evaluation, over-refund rejection, idempotence and interrupted-owner tests passed.

An exact quote anchors provenance but does not prove every surrounding claim. The proposed quote must still occur in the selected material. Where the writer partly paraphrases it, retain only a common exact substring of at least four codepoints from that quote or the selected material, and still require independent full-text review. Do not replace it with fuzzy similarity. User-provided material must not become the character's personal observation; one real writer made this mistake and the independent review rejected it. Model defer is limited to recent conversation completion; runtime activity may separately defer once.

Safety and initiative are distinct acceptance axes. A 15/16 model run was followed by two project-context positives choosing `pass/low_value`. The positive expectations remain `speak`; these are unresolved quality failures, not successful safety tests. A review that returns only booleans does not identify its exact rejection reason. Do not label a plausible actor/subject explanation as a confirmed cause or repeatedly sample until a passing result hides the failures.

Evidence: `packages/service/src/companion-invitations.test.ts`, `packages/service/src/learning.test.ts`, `bridge/dsh/tests/analysis.test.mjs`, `qualification/ts-runtime/invitations-probe.cts` and `reports/2026-10-28_b_natural_invitations.md`. Engineering checks and the described real cases verified once on macOS arm64. Prior holdouts used for tuning are subsequently regression cases; preserve failed runs and do not claim multi-day naturalness.
