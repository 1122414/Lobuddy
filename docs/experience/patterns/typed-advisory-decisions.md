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
