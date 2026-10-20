# Explicit sources must retain identity, not obsolete response bodies

## Signals and mechanism

A forgotten project fact can return through an old request response, engine session, summary, queued learner or proactive topic. Explicit source records alone do not remove those derived copies. Editing an unassigned record can also accidentally inherit an unrelated new-draft selection when empty identity is treated as falsy.

## Handling and applicability

Store replay fingerprints with an entity ID and resolve current state on replay; do not retain complete sensitive source response bodies in the transport cache. Creation remains idempotent in its repository; edits require revisions. Mark the appropriate source operations transient in the shared generated protocol only after these durable guarantees exist. This is a narrow exception to the default mutation-retention rule.

Invalidate derived summaries, blocked-source learning, topic preparations and engine mapping when a source is corrected, removed or expires. Recheck source validity after asynchronous model completion and before presentation. Track source-to-turn use so deleting a fact cannot leave a prior engine conversation as the effective authority. Project membership is explicit; distinguish an empty project ID from absence of an edited record.

macOS file pickers may return `/var/...` while the canonical path is `/private/var/...`. Canonicalize the picker-selected parent in the trusted main process, keep the final filename, then validate/read using no-follow descriptors. Do not resolve the final symlink and silently authorize its target.

## Evidence and limits

Verified once on 2026-10-19: `tests/test_projects.py` (28 cases), `desktop/tests/projects-smoke.cjs` (native picker, correction/forgetting/restart plus unassigned-delegation edit). Real-model checks in `scripts/smoke_personal_context.py` cover cross-session correction, same-name isolation and forgotten-source exclusion. Does not establish semantic deletion from the provider's infrastructure or unread external files; source URLs are explicit snapshots, not monitored feeds.

Never use a paginated recent-task view to invalidate persistent engine history. Resolve every source-to-turn association from the authoritative tables. `test_forget_retires_engine_even_outside_recent_task_page` verifies that clearing still works when the recent-task view has no entries; project edits retire bound/historical engine sessions and reject edits while that project is actively generating. Verified once with the 28-case project suite.
