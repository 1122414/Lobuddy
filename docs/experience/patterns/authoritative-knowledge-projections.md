# Keep authoritative knowledge separate from its projections

## Signals and mechanism

A removed memory remains in a Markdown file, or a disabled skill cannot be enabled again. Inspect the empty-result branch and the actual content authority. Returning early for an empty projection preserves stale facts; deleting the sole skill file discards the only recoverable source. SQLite `INSERT OR REPLACE` also deletes/reinserts rows and can cascade away lifecycle evidence.

## Diagnosis and handling

Keep canonical skill content in SQLite and treat workspace files as projections. Backfill only validated managed paths; missing historical content is an explicit recovery problem. Use an upsert that updates the existing row, preserve IDs and events, and test disable → edit → restart → enable. Empty generated memory projections must be cleared, while unrelated handwritten files are preserved. Test the last item, not only deletion from a nonempty list.

For model context, distinguish DSH `systemPrompt.context` (durable user-role snapshots in 0.1.5rc1) from scoped dynamic sections. Current memory uses a variable-backed system section, avoiding old snapshots and unintended template interpolation. Corrections invalidate prior summary injection without deleting historical source records. This does not erase original chat history or retract a model request already sent.

macOS path comparison must allow `/var` and `/private/var` to resolve to the same managed file. Compare resolved paths while separately rejecting symlinks in the derived managed path; do not use this observation to allow paths outside the workspace.

## Evidence and boundaries

Verified once on 2026-10-16, DSH 0.1.5rc1/macOS arm64. `tests/test_knowledge_service.py` covers projection deletion, summary invalidation, lifecycle/event retention, path aliases and escaped paths. `scripts/smoke_dsh_knowledge.py` verifies actual model recall/correction/deletion, active/disabled skill behavior, approval and restart. See `reports/2026-10-16_p4_knowledge.md`. Legacy files already deleted cannot be recovered by this change; historical absolute-path relocation requires a backed-up migration.
