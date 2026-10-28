# Proactive speech needs conversation handoff and distinct feedback

## Signals and mechanism

A companion shows a sourced topic in a pet bubble, but a short reply in the chat has no explicit link to that topic. A UI engagement event may also acknowledge the bubble without the user reading or responding to it.

Presentation state, conversational context and preference evidence are separate authorities. Clearing a notice and opening a window does not transfer the utterance into a session. Acknowledging navigation is not evidence of interest.

## Diagnosis and handling

Trace the complete path: displayed notice identity and source revision, click callback, window routing, selected session, submitted turn and context builder. Check where the actual character utterance and its valid source become available for follow-up. Keep background material distinguishable from user speech.

Design an idempotent handoff to the intended conversation, rechecking source scope, revision, expiry and forgetting barriers. Preserve enough topic context for short replies without reviving deleted source content. Validate multiple sessions and repeated clicks before judging real-model continuity.

Track display, navigation, actual topic continuation, explicit preference and silence separately. Use explicit preference as strong evidence; silence can justify temporary backoff but does not establish durable dislike. Do not infer a current learning bug merely because a field is named opened.

## Supporting case and validation status

Static inspection once on 2026-10-28, Lobuddy source at 6168928 (analysis-only HEAD 61c2be6):

- desktop/src/companion.tsx acknowledges opened and invokes the chat window action; desktop/electron/windows.ts shows quick chat without topic identity.
- desktop/src/useDesktop.ts sends the selected session and input. packages/service/src/companion/dialogue.ts supplies dialogue mode and boundaries, not the displayed invitation.
- packages/service/src/companion/policy.ts treats typing/conversation activity as opened when a notice exists. packages/service/src/companion/topics.ts does not learn a positive preference from opened; later/ignored apply cooldowns.

These established the missing explicit handoff in this inspected path and limited feedback semantics. They do not prove every old model follow-up failed: a prior conversation could independently contain enough context. At that scan no native/model reproduction or fix was performed.

See reports/2026-10-28_companion_projects_research.md, LS-10 and LS-12, for proposed acceptance cases. Recheck this conclusion after any session routing, context or invitation-contract change.

## A2 implementation and verification (2026-10-28)

`companionship.accept` now records a durable notice/session/message/source/revision association and saves the displayed text as assistant speech in one transaction. It reuses only an idle compatible session; project-scoped material never follows an unrelated selected project. The renderer selects the returned session before opening chat. RPC replay is transient; database identity owns idempotence and every replay rechecks source authority.

`CompanionHandoffs.context` revalidates before engine history opens and records each consuming turn. Revocation deletes the derived bubble, retires engine mappings, blocks source turns and clears derived summaries/memories; a `revoking` state resumes interrupted cleanup. Passive expiry also cancels active consuming turns. Keep mutation notification after the SQLite write and before derived-file refresh: a failed projection must not leave the old handoff valid. A pre-write epoch change alone cannot observe the replacement row.

Evidence: eight focused tests in `packages/service/src/companion-handoff.test.ts`, application composition/context and in-flight cancellation tests, and `desktop/tests/handoff-smoke.cjs`. The native isolated run clicked the real bubble, selected the correct project, completed three short follow-ups through governed DSH, restarted, and forgot the source without reactivating the notice. Full root check passed 277 tests. See `reports/2026-10-28_a2_proactive_handoff.md` and its JSON evidence. Verified once on macOS arm64; not a multi-day naturalness or preference-learning result.

The real-model replies still exposed a raw source ID and implementation-oriented explanations. Context continuity and conversational quality need distinct acceptance checks; keep these examples for stage B rather than describing successful handoff as natural companionship.

## B expression follow-up (2026-10-28)

The handoff context now asks for one or two sentences on short replies, uses human-readable source/project titles, preserves unfinished status and avoids unsolicited task proposals. Re-running the same native three-round scenario retained the offline-feature decision and the fact that its test had not happened, without raw source IDs or permission/budget explanations. See `reports/2026-10-28_b_native_followups.json`. This verifies this short sequence once, not every future conversation.

The original native companionship script relied on a generic fallback bubble after nickname conversations. With explicit pass/defer, a nickname is not enough to justify an invitation. The updated test supplies a real synthetic shared experience and lets the actual governed model select and review it. A separate offline pending-event fixture isolates generation/display from macOS foreground activation; it must not be described as proof that an actual OS return event fired. Model call failures and non-generation need distinct diagnostics rather than merely increasing the UI timeout.

The real long bubble exposed a separate UI cause: one flex row let text and the source button shrink into narrow columns and pushed the close control outside the viewport. The native click failed with an outside-viewport error, then the notice expired. Keep a bounded scrollable text row and a stable control row inside the existing window; reserve the close control above the source overlay. `desktop/tests/handoff-smoke.cjs` now checks every button's bounds, toggles the source preview and completes the handoff with a 60-codepoint quote. Both that test and actual generated-bubble dismissal passed once; before/after screenshots and JSON are linked from the B report. The newest three-round model output still contains paragraph breaks and more than two sentences, so this UI/continuity pass does not complete B2 expression quality.
