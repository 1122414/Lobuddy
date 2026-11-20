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

## Boolean reviews and unsupported story facts (B2, 2026-10-28)

The first B2 comparison matched all 21 automated action/keyword expectations, yet manual reading found an unsupported statement: a story title and a fearful fox protagonist became a fox already boarding a paper boat. The independent three-boolean review also passed it. Adding an explicit rule about fictional facts did not fix that retained counterexample; the next run matched 21/23 and also rejected an otherwise plausible coffee topic. Automated action/keyword coverage and a model's approval are not factuality measurements.

An initial assertion/evidence list passed four targeted real cases, including null/grounded=false for the unsupported action, but then matched only 20/25 in a full run: it treated opinions and hypothetical questions as unsupported facts. Adding explicit fact/opinion/hypothesis/question types reached 22/25; remaining misses exposed attempt-versus-completion wording, duplicate fact/opinion classification and an emotion judgment misclassified as opinion. Preserve these runs rather than reporting the targeted four as complete validation.

The current review requires one to eight exact utterance spans, each with a type. Facts require exact non-null source evidence; opinions, explicit hypotheses and open question parts require null evidence. Reject absent utterance spans, invented quotes, an empty/excessive list or an old missing-field shape. Clarify the same user-provided source perspective for writer and reviewer; preserve attempts and plans rather than implying completion. A subjective evaluation of an idea differs from a claim about the user's actual emotion or an observation: the latter still needs factual support. See `reports/2026-10-28_b2_conversation_quality.md` for current verification status.

This structure improves inspectability and catches literal boundary failures; it still depends on the model to extract every factual assertion and judge whether the quote actually supports it. Exact source text does not guarantee semantic entailment. Keep new samples and human review, preserve failed runs, and never count a quality-only probe as native delivery coverage.

The same separation matters after adding two bounded drafts: a later 25/25 action/keyword/review run still omitted an attempt qualifier, converted a project plan into personal intention, and implied visual observation of text-only material. Those actual utterances became three additional review regressions. A rule-only follow-up matched 23/28, with two retained review errors and three positive topics rejected. The working change now supplies project versus personal provenance explicitly and uses typed negative examples; its completion requires new evidence. Preserve all these measurements rather than treating one passing automatic run as semantic validation. See `reports/2026-10-30_b2_hypothesis_shape.json` and `reports/2026-10-30_b2_qualifier_boundaries.json`.

The later source/channel experiment (`reports/2026-10-30_b2_separated_full.json`) matched 25/28 and still approved a project plan as personal intention. A safe bookmark draft failed strict review format, while a natural pinecone paraphrase failed the literal shared-quote floor before its alternate reached review. These show different failure mechanisms; changing instructions alone does not diagnose them. Three isolated low-reasoning experiments also failed through truncation and wrong judgments (0/4 at 1024 output tokens, 2/4 at 2048, then 1/4 with shortened instructions); those reasoning/budget changes were reverted. Do not recommend increasing the production budget on this evidence. The text-only visual-language preflight covers known phrases, with possible figurative-language false positives; it is not a general factuality proof. B2 remains unverified for completion.
