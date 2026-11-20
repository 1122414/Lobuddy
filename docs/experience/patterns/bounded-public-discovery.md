# Public discovery: independent budgets, source time and asynchronous ownership

## Signals and mechanism

A public API returns 403 although the application's own daily ledger has capacity; a manual refresh can outlive RPC timeout; canceled requests complete after the user changes sources; an open panel continues showing expired cache entries.

These are separate boundaries. The application's allowance does not reserve the upstream service's shared-IP quota. Publication time is not update time. A request, a refresh batch, its persisted attempt and a mounted UI each have distinct lifetimes; canceling only the current socket does not cancel the next iteration of a manual batch.

## Diagnosis and handling

- Classify a fixed public request using status and bounded public rate-limit headers. Do not log credentials, user content or raw provider failures. On 2026-10-30, GitHub's API returned 403 with remaining=0 and a reset time even though this isolated application had just started. Keep `unavailable` distinct from a successful empty release list. Do not silently add credentials or reset local attempt history.
- Reserve the bounded attempt synchronously before I/O. Keep source cooldown and daily allowance across restarts, failures and source removal/re-addition; revisions prevent delayed results from reviving removed sources. Failure to persist the reservation must prevent networking.
- Put DNS resolution under the request's cancellation/deadline before opening a socket. Validate all resolved addresses, then pin the selected result to the socket; keep the same checks for redirects. Abortable DNS waiting does not promise to cancel the OS resolver itself.
- A manual batch returns an immediate state acknowledgment and has one asynchronous owner. Capture the activity generation, stop remaining sources after cancellation, and expose completion by transient reads. This avoids fitting multiple ten-second network requests inside one twenty-second RPC.
- Distinguish ambient activity from a new foreground action. `useEngagement` repeats a typing signal for eight seconds after any form input. Canceling every read on each heartbeat can cancel a manual refresh made immediately after saving the form. Explicit manual reads ignore those ambient heartbeats; actual task start, configuration revocation, sleep and close still cancel. The original native interrupted status is consistent with this confirmed path; its exact callback was not separately traced. The targeted test reproduces this path, and the subsequent native run read both AIRI and ComfyUI.
- Reconcile the mounted panel with one local read in flight. Preserve unsaved form inputs, keep their configuration revision, and reject cross-window stale saves. Ignore reads started before a mutation and stop polling on unmount. Reconciliation is needed for time-based expiry even without a new event.

## Supporting checks and limits

`packages/service/src/discovery.test.ts` verifies publication admission, replay/revision, durable budget, source intervals, shutdown/cancellation, nonblocking batch acknowledgment and failed persistence. `packages/service/src/tools.test.ts` verifies cancellation before a pending DNS lookup opens a socket, alongside the existing private-address/redirect/body-limit checks. `desktop/tests/discovery-panel.cjs` runs the production React panel with synthetic IPC and checks reconciliation, draft preservation, conflict, late responses, plain text and controlled links.

Verified once in the final C1 independent snapshot (309 checks), the mixed working tree (315 checks) and an isolated Chrome component run. The first native test called RPC before handshake; waiting for the existing service-connected state allowed configuration and real read attempts. Later native runs obtained actual AIRI and ComfyUI releases, but no complete native run is marked passed: upstream limits recurred, and the initial memory assertion had a separate fixture error. See `reports/2026-10-30_c1_public_discovery.md` for each retained result.

The complete application bootstraps a system identity through the memory gateway. A native startup-only probe observed one `bootstrap/system_profile` item before discovery was enabled and with zero source reads. A low-level Store fixture starts empty; that does not establish the application's baseline. To verify that news does not mutate memories, capture the complete initial records and compare them after the lifecycle, instead of assuming zero or comparing only counts. The corrected final comparison is still pending because the next native run stopped at public networking; do not report it as passed.

This mechanism applies to bounded public caches. It does not validate general news relevance, model factuality, proactive speech, authenticated/private-source access or a second database writer. Official sources: [GitHub public Releases](https://docs.github.com/en/rest/releases/releases#list-releases), [shared-IP rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
