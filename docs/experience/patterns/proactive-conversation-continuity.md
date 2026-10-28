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

These establish the missing explicit handoff in this inspected path and limited feedback semantics. They do not prove every model follow-up fails: a prior conversation may independently contain enough context. No native/model reproduction was performed, and no fix was applied.

See reports/2026-10-28_companion_projects_research.md, LS-10 and LS-12, for proposed acceptance cases. Recheck this conclusion after any session routing, context or invitation-contract change.
