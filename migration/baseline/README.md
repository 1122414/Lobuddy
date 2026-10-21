# TypeScript migration baseline

Frozen from `7195718` on 2026-10-21. These are synthetic fixtures and historical identifiers, not user data. Do not modify expected results to make the new implementation pass. Track implementation progress outside this directory.

| File | Meaning and limitations |
|---|---|
| `methods.json` | All 110 request methods, parameter model, result type, transient retention flag and implementation stage. Test file references locate coverage; the fallback headless test is not proof of coverage for an individual method. |
| `schemas.json` | 119 Pydantic JSON schemas, including nested definitions. Runtime coercion and custom validators are not fully represented by JSON Schema. |
| `cases.json` | 988 observed Pydantic input outcomes, normalized defaults, extra-field rejection, null/type and Unicode boundaries. These are seeds for contract tests, not complete business or response/event tests. |
| `validators.json` | 15 custom validators requiring explicit semantic migration. Hashes identify the original AST; they do not implement validation. |
| `tests.json` | All 1077 collected pytest cases. Stage ownership is initially classified by source module; every item remains pending until equivalent assertions or an explicit retirement review are recorded. Framework-specific labels never authorize dropping business assertions. |
| `database.json` | 77 SQL objects from a synthetic initialized application and desktop migrations, user_version 2. Includes FTS shadow tables; this snapshot is an inventory, not a script to replay blindly. |
| `manifest.json` | Source revision, counts and SHA256 of frozen JSON files. |

Verification: `node scripts/ts/verify-baseline.mjs`. Collection command actually run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --collect-only -q tests` (1077 cases). Input outcomes were executed with the existing Pydantic models; database schema was extracted from a disposable synthetic database with fake credentials and no model requests. This stage did not rerun the full Python test suite. Earlier 1077/16/8 passing results remain historical evidence, not TS acceptance.

## Migration tracking requirements

For each test, record the original node ID, replacement TS test name/path, stage, status and evidence. For an obsolete Qt/nanobot assertion, record its reason and the replacement observable behavior. For each RPC, add response/event/error fixtures and idempotence tests; request validation alone does not close TS-01. Freeze historical inputs separately from evolving status records.

| Acceptance | Regression mechanisms to preserve | Existing evidence index |
|---|---|---|
| TS-01 | Transient reads do not exhaust retention; fingerprint mismatch rejects; event gaps resync without replay | `docs/experience/patterns/protocol-request-retention.md` |
| TS-02 | WAL-consistent snapshots, unknown versions and corrupt input rejected, relocated bundle independent | `docs/experience/patterns/native-upgrade-boundaries.md` |
| TS-03 | Cancelled startup ownership, terminal states and transactionally unique settlement | `docs/experience/patterns/async-lifecycle-ownership.md`, `durable-effect-settlement.md` |
| TS-04 | Forgetting invalidates derived context, replay and engine session mappings | `docs/experience/patterns/explicit-source-lifetime.md`, `authoritative-knowledge-projections.md` |
| TS-05 | Shared process ownership, no accidental approval cancellation, preserve manual reading position | `docs/experience/patterns/multiwindow-ownership.md`, `chat-scroll-ownership.md` |
| TS-06 | Original timezone, DST gaps/folds; advisory decisions cannot grant authority | `docs/experience/patterns/calendar-wall-time.md`, `typed-advisory-decisions.md` |
| TS-07 | Immutable versions, objective improvement, no holdout edits or unknown-write replay | `docs/experience/patterns/verified-workflow-promotion.md` |
| TS-08/09 | Late callbacks, microphone release, interrupted soak is not a pass | `docs/experience/patterns/async-lifecycle-ownership.md`, `process-terminal-evidence.md`, `docs/experience/unresolved.md` |
| TS-10 | Exact runtime versions, binary relocation and data/credential boundary | `docs/experience/patterns/runtime-version-boundary.md`, `native-upgrade-boundaries.md` |

Physical ten-round voice, speaker echo, latency and uninterrupted two-hour voice acceptance remain pending. Existing UI capability does not establish these results. Old-main-only functionality excluded from the DSH merge is outside this baseline.
