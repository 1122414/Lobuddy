# CORE KNOWLEDGE BASE

**Scope:** Domain logic layer — 14 subpackages, 30+ modules, zero UI dependencies (except Qt signals)

## STRUCTURE

```
core/
├── agent/          # AI boundary: nanobot adapter, gateway, sub-agents (10 files)
├── models/         # Pydantic domain models (6 files)
├── storage/        # SQLite repos, crypto (9 files)
├── tasks/          # TaskManager + TaskQueue (2 files)
├── game/           # GrowthEngine: EXP/level/evolution (1 file)
├── personality/    # 5-dimension trait engine (1 file)
├── abilities/      # 7 unlockable abilities (1 file)
├── services/       # PetProgressService, PetAssetService (2 files)
├── safety/         # Guardrails: path/shell/URL validation (1 file)
├── tools/          # ToolPolicy: command allowlist (1 file)
├── events/         # Async EventBus + event dataclasses (2 files)
├── config/         # Pydantic Settings model (1 file)
├── logging/        # SensitiveDataFilter (1 file)
├── runtime/        # TokenMeter (1 file)
├── reserved/       # Stubs: FocusCompanion, MemoryCardStore, MessageHighlight (3 files)
├── pet_state_manager.py  # Pet display state machine
└── time_format.py        # Unified time formatting utilities
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add AI capability | `agent/` | Use `NanobotAdapter`, never call nanobot directly |
| Add domain model | `models/` | Pydantic v2 BaseModel, datetime objects |
| Add DB table/repo | `storage/` | Raw SQL, repository pattern, `get_database()` singleton |
| Add task feature | `tasks/` | `TaskManager` orchestrates, `TaskQueue` serializes |
| Add growth mechanic | `game/growth.py` | EXP table, level thresholds, evolution stages |
| Add personality trait | `personality/` | Keyword-based detection, 5-dimension system |
| Add ability | `abilities/` | Requirement system: level/stage/trait gates |
| Add security check | `safety/guardrails.py` | Path traversal, SSRF, shell injection |
| Add tool policy | `tools/tool_policy.py` | Command allowlist, git subcommand safety |
| Add event | `events/` | Async pub/sub, `EventBus.publish()` / `subscribe()` |

## CONVENTIONS

- **Repository pattern:** One repo class per domain (`PetRepository`, `ChatRepository`, etc.)
- **Singleton DB:** `get_database()` returns shared `Database` instance
- **JSON columns:** Complex types (personality) stored as JSON strings in SQLite
- **No ORM:** Raw SQL with `with self.db.get_connection() as conn:` pattern
- **Manual commit:** Always `conn.commit()` after write operations
- **Pydantic v2:** All models use `BaseModel`, datetime as objects, `.model_dump_json()`
- **No UI imports:** Core must not import from `ui/` (exception: `task_manager.py` uses `QObject`/`Signal`)

## ANTI-PATTERNS

- Do NOT bypass `nanobot_adapter.py` for AI calls
- Do NOT use ORM (raw SQL preferred)
- Do NOT forget `conn.commit()` after writes
- Do NOT store large blobs in SQLite
- Do NOT import from `ui/` (except Qt signals in tasks/)
- Do NOT use dicts for structured data (use Pydantic models)
- Do NOT bypass Pydantic validation
- Do NOT store UI state in domain models

## NOTES

- `core/tasks/` uses `QObject`/`Signal` — this couples "pure core" to Qt
- `core/reserved/` contains stub interfaces for planned features (DO NOT implement yet)
- DB schema created on startup; no Alembic/migrations
- `pet_state_manager.py` and `time_format.py` are root-level core modules (not in subpackages)
- Sub-agents run in `multiprocessing.Process` with result-file IPC (see `agent/subagent_factory.py`)
