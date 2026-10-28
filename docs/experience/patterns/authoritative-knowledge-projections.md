# Keep authoritative knowledge separate from its projections

## Signals and mechanism

A removed memory remains in a Markdown file, or a disabled skill cannot be enabled again. Inspect the empty-result branch and the actual content authority. Returning early for an empty projection preserves stale facts; deleting the sole skill file discards the only recoverable source. SQLite `INSERT OR REPLACE` also deletes/reinserts rows and can cascade away lifecycle evidence.

## Diagnosis and handling

Keep canonical skill content in SQLite and treat workspace files as projections. Backfill only validated managed paths; missing historical content is an explicit recovery problem. Use an upsert that updates the existing row, preserve IDs and events, and test disable → edit → restart → enable. Empty generated memory projections must be cleared, while unrelated handwritten files are preserved. Test the last item, not only deletion from a nonempty list.

For model context, distinguish DSH `systemPrompt.context` (durable user-role snapshots in 0.1.5rc1) from scoped dynamic sections. Current memory uses a variable-backed system section, avoiding old snapshots and unintended template interpolation. Corrections invalidate prior summary injection without deleting historical source records. This does not erase original chat history or retract a model request already sent.

macOS path comparison must allow `/var` and `/private/var` to resolve to the same managed file. Compare resolved paths while separately rejecting symlinks in the derived managed path; do not use this observation to allow paths outside the workspace.

## Evidence and boundaries

Verified once on 2026-10-16, DSH 0.1.5rc1/macOS arm64. `tests/test_knowledge_service.py` covers projection deletion, summary invalidation, lifecycle/event retention, path aliases and escaped paths. `scripts/smoke_dsh_knowledge.py` verifies actual model recall/correction/deletion, active/disabled skill behavior, approval and restart. See `reports/2026-10-16_p4_knowledge.md`. Legacy files already deleted cannot be recovered by this change; historical absolute-path relocation requires a backed-up migration.

## Activation is separate from storage correctness

A migrated setting or class is not evidence that its scheduler runs in the new entrypoint. The 2026-10-16 Fibona comparison found memory/skill maintenance wired in legacy `app/main.py` but not in `app/service.py` or the new application service, even though legacy fields remain visible in settings. The current experience instance had active memory injection and a system identity row, but no user-profile memories; its automatic skill-candidate setting was false. Verify effective settings, composition-root callers, persisted counts and recent execution evidence independently. Do not infer complete automatic learning from passing CRUD/projection tests. The 29 related tests still passed; they establish existing contracts, not missing orchestration. See `reports/2026-10-16_fibona_learning_gap_review.md` for the bounded findings and unimplemented remedies.

## Forgetting must fence derived work and scope, not only delete a projection

E1 introduces source-linked relations. Source deletion/correction can race an already-issued summary call, and a shared profile projection can leak a session-scoped preference into other sessions. Keep source barriers and an epoch checked after auxiliary model completion; filter scoped relation records in hot context, cold retrieval and shared projections. Retain provenance through the gateway rather than labelling all automatic writes manual. `tests/test_relationship.py` verifies scope, source admission, correction/restart and late-output fencing; `scripts/smoke_relationship.py` twice verified real DSH extraction → correction → new-session recall → forgetting in synthetic databases on 2026-10-16. This is not deletion of historical DSH execution files, provider-held inputs or backups. The UI's source-chat deletion explicitly targets Lobuddy chat rows.


E5 cross-stage validation: new learning consumers must reuse the source barrier, not merely the relationship extractor. `tests/test_evolution_integration.py` verifies that forgetting a correction also stops skill/workflow source jobs, rejects re-extraction, clears candidate revisions and removes the exact originating text from disabled derived skill versions and archives. New model proposals check the relationship epoch after awaiting a response. This covers derivations with recorded source IDs; independently edited text without provenance cannot be automatically identified as a derivation.

A second E5 boundary is recoverable legacy content: when the current skill body exists only on disk, snapshot that actual version inside `get_content` before the first edit increments the version. `TestEvolutionIntegration.test_legacy_current_skill_body_is_snapshotted_before_first_edit` verifies v7 is recovered and v8 is the edit, without inventing v1–v6. Cleanup reads blocked source text solely to erase derived copies; normal retrieval continues to exclude it.

## Retrieval admission is separate from correct storage (2026-10-28)

Signals: a memory exists and a keyword query finds it, but a short conversational question does not include it in the generated context. Inspect budget admission and query construction separately before changing storage, projections or model providers.

At the scan baseline, TS `KnowledgeService.context()` computed remaining episodic space from the current user input length times `memory_prompt_budget_percent`, then subtracted fixed profile/summary space. At the default 0.2, short input could have no remaining space. Its repository call also passed the full input into the default substring LIKE search, so a natural question need not match even when a shorter keyword did. These were separate admission restrictions; broadening retrieval alone did not fix a zero budget.

Verified once with an isolated current-build probe at `6168928`: default runtime settings, bootstrap, and a synthetic episodic memory saved through the gateway. Query `星桥` found one row; `星桥项目上次决定了什么` found zero; neither context contained the target fact. Supporting paths: `packages/service/src/knowledge/service.ts`, `packages/service/src/storage/memory.ts`; full inputs and results are in `reports/2026-10-28_product_state_and_evolution.md` (LS-02). This establishes the context-builder limitation, not universal model recall failure: relation context, project context, engine history and explicit history search are different paths.

The scan did not apply a repair. A1 subsequently reserves a bounded episodic share from `memory_prompt_budget_chars * memory_prompt_budget_percent`, including its heading and separators, independently of utterance/profile size. Zero still disables episodic injection. `MemoryRepository.recall()` uses bounded lexical terms and filters scope, expiry and source barriers before limiting ranked candidates; oversized candidates do not block later fitting ones. Settings metadata documents the corrected budget basis.

ICU segmentation is not automatically a query strategy: the actual runtime split 星桥 into single characters, and naive grouping joined a trailing 的 to the name. Group adjacent non-function single Han characters while separating stop words. This is a lexical heuristic, not semantic retrieval; vague follow-ups need the explicit conversation handoff rather than arbitrary old facts.

Verified once by the eight `companion-foundations.test.ts` cases plus current root checks (262 tests) on 2026-10-28. The original short queries now include the synthetic fact; privacy/expiry/barrier filters, corrected/deleted sources and tiny/zero budgets are checked. See `reports/2026-10-28_a1_companion_foundations.md`. This does not establish universal recall quality or real-model continuity; A2 and subsequent quality evaluations remain necessary.
