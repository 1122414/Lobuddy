# Extract explicit dialogue intent without treating every mention as a command

## Signals and mechanism

An exact short instruction updates durable conversation mode, but adding personal context or a polite ending leaves the mode unchanged. An immediate model reply can still sound appropriate, hiding that later proactive decisions lack the requested boundary.

Whole-input regular expressions missed explicit clauses such as 我今天有点累，先听我讲就好 and 今天不想聊工作 at 6168928. Expanding to an unanchored substring would also interpret quoted or hypothetical speech as a real instruction.

## Diagnosis and handling

Reject quoted, hypothetical, reported and interrogative input before splitting ordinary sentence clauses. Match complete explicit clauses, normalize limited polite endings, and keep session mode distinct from topic boundaries. Preserve existing expiration and removal behavior; these states do not cancel authorized tasks.

Do not blindly strip the final Chinese particle character. 酒吧 is a noun; ICU also splits 知了 into 知 and 了. A1 only strips a standalone final particle when at least two subject characters remain. This conservative heuristic does not cover all linguistic ambiguity; uncertain or unsupported wording still needs later typed semantic handling, not a claim of universal understanding.

## Evidence and applicability

Verified once on 2026-10-28: `packages/service/src/companion-foundations.test.ts` checks surrounding context, polite endings, mode changes, session separation, midnight expiry, permanent boundaries, removal and negative cases. Existing `companion-content.test.ts` verifies source-backed invitation suppression by boundaries. Root check passed 262 tests.

`desktop/tests/dialogue-smoke.cjs` passed with the two original natural phrasings, observing the mounted native companionship panel switch to listening and quiet, then remove the boundary. This test uses isolated data/profile and a deterministic workflow with unused synthetic credentials. It verifies state/UI behavior, not real-model empathy or physical voice quality. See `reports/2026-10-28_a1_companion_foundations.md`.
