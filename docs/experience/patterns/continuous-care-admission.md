# Continuous care: sourced facts and scheduling state have different authority

## Signals and mechanism

A companion needs to follow up on an ordinary personal update without treating a quoted intention, another person's goal, or an assistant assertion as a user fact. A model-proposed date cannot be the authority for scheduling. A recent-message page cannot be the authority for forgetting old follow-ups.

## Handling and limits

Admit only exact user-source fragments and source-contained subjects through MemoryWriteGateway. Keep scheduling and revision state separate from factual memory; scope both to the originating session/project. Resolve supported dates from the source timestamp and saved timezone. Unknown duration gets the next day's review window; unknown date gets a bounded 48-hour revisit. Validate source content, memory revision, barriers, project association and expiry on reuse.

Persist preparation before gateway writes and recover only if the fact exists and remains valid. A missing fact invalidates preparation. Revision-guarded updates use durable request fingerprints and return the current record on replay. Reconcile all stored follow-ups, not just the UI's recent page; redact invalid titles and remove their fact projections.

## Supporting cases and verification

`packages/service/src/care.test.ts` covers ordinary admission, adversarial/third-party/sensitive sources, restart idempotence, revisions/replay, correction/forgetting/project movement/expiry, interrupted preparation and v4 migration backup/rollback. Existing storage tests preserve the original migration fingerprint. Date and timezone cases use a fixed source instant. These are deterministic checks, verified once on 2026-11-02; they do not validate model extraction quality, native delivery or sustained naturalness. The S2 report records independent-stage checks separately from the mixed working tree.

## Delayed analysis and source clock (2026-11-02)

The legacy chat display timestamp has no offset. Reinterpreting it with a newly selected policy timezone changes the event date; assigning a fact's default creation time during delayed analysis also makes an old update appear recent. `storage/turns.ts` now writes a validated absolute instant and the saved IANA timezone in the same transaction as the user message. Care admission, candidate age and human-readable model context use that original instant. Forgetting removes the linked clock metadata. Historical messages without this metadata still fall back to the saved policy timezone; the original timezone cannot be reconstructed from those rows.

`application.test.ts` verifies clock/message atomicity, restart and forgetting; `care.test.ts` verifies a New York source after switching policy to UTC and delayed analysis preserving the fact/candidate time. Exact source identity also owns idempotence: a later analysis choosing a different title for the same source must not create a second follow-up. Verified once with the 334-test mixed-tree root check; this is not a claim of real-model date comprehension.
