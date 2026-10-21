# Preserve recovery boundaries during native upgrades

## Reject incompatible schemas before any initialization (2026-10-21)

The old desktop database initializer accepted newer versions before later runtime-ledger checks rejected them. Initialization could therefore precede the compatibility decision. The transitional initializer now checks `DESKTOP_SCHEMA_VERSION` before DDL or task recovery. `TestBackupMigration.test_newer_database_is_rejected_before_any_legacy_initialization` verifies unchanged bytes for a synthetic newer database. This protects the current compatibility source, not previously distributed binaries. Always pair a rollback executable with its own backup.

The TS importer uses a separate directory and version 3 marker. A separate SQLite exclusive transaction owns execution; real process termination releases it without deleting lock files. Imported running work becomes interrupted and authorized delegations require review; engine associations receive recovery markers. Later domain code must enforce those markers before resuming. Frozen records from the Python public service verify IDs, relationship revisions, source barriers, skill/workflow versions and files. See `packages/service/src/storage.test.ts` and `reports/2026-10-21_t3_typescript_storage.md`. Verified once on macOS; real user data and final UI migration remain untested.

## Signals and mechanism

Copying SQLite bytes while WAL is active can omit committed rows. Restoring the business DB without DSH session files leaves engine-session mappings pointing to missing execution records. Removing plaintext credentials before checking the native store can leave a working installation unable to authenticate.

## Handling

Use SQLite online backup, private file permissions and a complete checksummed manifest. Stop the runtime before copying its session files. Import into a fresh sibling directory, validate paths and integrity, then atomically rename the directory into place. Never mutate the original DB during an import. Mark the schema version so the transitional legacy entry refuses upgraded databases. An exact snapshot restore uses the matching old program and restored data; it is not a reverse migration.

Write and read back every credential in the app's own Keychain namespace before removing any legacy binding. Preserve the entire original `.env` and DB credential rows when native storage fails. Parse dotenv bindings rather than deleting lines, because quoted multiline values span lines. Detect concurrent edits before replacing the file. Never pass a secret in process arguments or return it to the renderer.

P8 exposed a second credential boundary: a primary LLM key in the environment must not suppress an optional Fish key in Keychain, and an older stored optional key must not overwrite its explicit replacement. Resolve precedence independently per field. Both directions are covered by `tests/test_voice_service.py`; configuration unit tests mock native storage and use temporary directories. The legacy adapter fixture also required explicit data/log paths: a temporary workspace alone still allowed memory projections to write the checkout's default data directory. After correcting that fixture, full regression passed with the original projection unchanged.

## Supporting observations

The old full-suite compile check used cwd-relative source paths and failed when tests were run in an isolated directory to avoid writing test memory into user data. Resolve code paths from `__file__`; keep mutable fixtures in temporary directories.

Google's unauthenticated HTML search returned a navigation-only page and DuckDuckGo rejected the request in this environment. A successful HTTP response is not proof of useful search results. The bounded Bing RSS path returns structured items and source links; reject missing items and XML entity declarations. Recheck availability instead of treating one provider's success as universal.

## Evidence and limits

Verified once on macOS arm64, 2026-10-16. `tests/test_upgrade_data.py` verifies idempotent imports, corruption rejection, stopped-runtime backup, unchanged source and credential failure preservation. `scripts/smoke_native_capabilities.py` verifies synthetic native Keychain items, opening a disposable document and public web reads. The real legacy DB was backed up/imported/restored with identical pet/session IDs and values. Secrets are not included in experience records. See `reports/2026-10-16_p5_capabilities.md`. Windows credential storage and public distribution signing remain separate acceptance work.

## Default entrypoints and readiness can still target the old runtime

On 2026-10-19, changing pyproject entrypoints did not update the already-installed `.venv/bin/lobuddy`; editable-install metadata must be refreshed too. The old health command invoked legacy bootstrap, so using it against desktop data could initialize the wrong runtime. Keep legacy bootstrap available for its own entry, use a read-only DSH diagnostic for the default command, and share settings decoding rather than silently ignoring database overrides. `tests/test_desktop_health.py` verifies no directory creation, corrupt DB preservation, stored settings, redacted errors and no Qt/nanobot imports; the bundled interpreter check also passed. This checks local readiness, not provider connectivity or real audio devices.

## Test isolation includes every writable path

On 2026-10-21, `tests/test_53_phase1_verification.py::TestSkillFileCleanup::test_archive_skill_removes_original_file` set temporary workspace and skill paths but omitted `skill_archive_dir`. Its fixed-content archive appeared under the checkout's default `data/skills/archive/`. Set that field explicitly and assert the resulting archive is under the temporary directory; do not merely hide the artifact with an ignore rule. The existing artifact was preserved outside tracked paths. The targeted 47-test run and subsequent 1077-test full regression passed in isolated snapshots; this verifies this fixture, not all possible default-path consumers.

Independent commits must be tested with only their staged content and earlier commits: a full dirty checkout can mask missing protocol consumers or package files. This cleanup used snapshots to validate intermediate voice wiring before companion additions, then relocated the final runtime. Preserve unfinished physical acceptance separately from implementation commits; snapshot tests do not establish microphone quality or two-hour voice stability. See `reports/2026-10-21_commit_cleanup.md`.

## T4: directory handles and bounded reads

Node path validation followed by a pathname write does not replace Python's descriptor-relative traversal. macOS `/dev/fd/N/child` was tried and returned ENOENT. The TS tool uses fixed Koffi bindings to `openat`, `mkdirat`, and directory enumeration instead; no model-supplied native symbol or library is accepted. Open each parent with NOFOLLOW, verify regular-file type and hard-link count before truncating, and keep writes exclusive for classified copies. Canonicalize existing ancestors of protected roots: `/var` and `/private/var` aliases otherwise produce mismatched protection prefixes. This implementation is qualified only on macOS arm64.

`readPrivate` now bounds bytes during reading and rejects FIFO without blocking, rather than relying solely on an earlier stat. Tests: `packages/service/src/tools.test.ts`; actual file tools ran in Electron through `qualification/ts-runtime/task-probe.cts`. Verified once, with isolated path/approval/symlink/hard-link/FIFO cases and native tool execution; arbitrary concurrent filesystem attackers and other platforms are not claimed covered.

## Preserve identity and native descriptor ownership (2026-10-21 T5)

A language port must preserve the serializer and text rules used by persisted identity, not only the parsed value. Pydantic float timestamp fields retain integral `.0`; Python Unicode casefold expands characters that JS lowercasing does not. Use the frozen legacy rules for old request hashes and UUID inputs. `projects.test.ts` and `relationship.test.ts` contain concrete compatibility checks; the static casefold table records Unicode 15.0 provenance. Do not apply this serialization rule indiscriminately to unrelated fields. Verified once.

In a Node worker with unmanaged descriptor tracking, calling `fs.closeSync` on a descriptor returned by native `openat` emitted “closed but not opened in unmanaged mode”. Keep close ownership aligned: the fixed libc wrapper closes its own descriptors; Node closes the root descriptors it opened. Full T5 isolated-worker regression passed without the warning. This evidence concerns macOS arm64, not an untested platform mapping.

## Legacy skill directory aliases (2026-10-21 T9)

The TS skill reader resolved legacy directory aliases, but the skill writer compared the stored pathname literally against the canonical workspace. `tests/test_knowledge_service.py::TestSkillLifecycle::test_legacy_path_alias_targets_same_managed_file` exposed the missing parity: disabling a skill failed both with a workspace alias and with macOS `/var` versus `/private/var` spelling. Two TS reproductions failed before the fix.

`SkillManager.path` now admits only aliases whose resolved parent and basename match the managed target. It normalizes the stored projection path and continues to use the guarded workspace writer; it does not write through the legacy alias. An unrelated external path is still rejected, and an absent body cannot be enabled. Tests in `packages/service/src/skills.test.ts` retain IDs and actual historical versions (5→6 without invented 1–4). Together with companion-content regressions, 13 checks passed once. This is compatibility for trusted stored path aliases, not permission to follow arbitrary links in file tools.
### Empty managed directories after disabling a skill (T9)

The old Python skill cleanup removed an empty skill directory; translating only file unlinking left that behavior behind. A dedicated `skills.test.ts` assertion reproduced the regression. The descriptor-relative file layer now uses Darwin `unlinkat` with `AT_REMOVEDIR` (`0x0080` in the local SDK), so the kernel rejects nonempty directories and no recursive cleanup can remove user notes. ENOENT/ENOTEMPTY are benign; other errors keep the projection operation pending. Re-enable recreates the projection from SQLite. Verified once on macOS arm64 with empty/nonempty/archive cases and tool regressions; flags are platform-specific and must not be copied into another OS backend.

## Legacy file authority during a language migration (2026-10-21 T9)

A SQLite import alone does not cover an old bootstrap that still admitted handwritten USER.md. Read the old composition path, not only repositories: the Python MemoryService constructor imported this file before writing projections. The TS bootstrap initially omitted it. Current `knowledge/legacy.ts` uses bounded descriptor-relative reads, checksummed exclusive private backups and a durable import marker. Batch rows and the marker commit together; projection writes happen afterward. Generated projections are never authoritative input, and removing all imported rows cannot enable reimport. Invalid historical question-word identities are deprecated without deleting unrelated facts.

An initial implementation wrapped the existing single-row repository save in another transaction; Store correctly rejected the implicit nesting. The repository now owns a batch transaction and the gateway sanitizes before admission. A SQL trigger failing the second insert proves rollback leaves no imported rows and preserves the handwritten source; retry, restart, forget, disabled migration, generated source and symlink cases passed once in `packages/service/src/knowledge.test.ts`. Full Node checks passed in both the workspace and an independent source snapshot. Backup files are rollback material, not future learning sources.
