# CORE KNOWLEDGE BASE

**Scope:** Domain logic layer — 20 subpackages, 60+ modules, zero UI dependencies (except Qt signals)

## STRUCTURE

```
core/
├── agent/          # AI boundary: nanobot adapter, gateway, sub-agents (10 files)
├── models/         # Pydantic domain models (6 files)
├── storage/        # SQLite repos, crypto (10 files)
├── memory/         # Structured memory + user profile (15 files, 1,706 lines) — v5.2
├── skills/         # Skill lifecycle management (9 files, 771 lines) — v5.2
├── services/       # PetProgressService, PetAssetService, ThemeGenerator (4 files)
├── tasks/          # TaskManager + TaskQueue (3 files)
├── config/         # Pydantic Settings model (2 files)
├── focus/          # Focus companion mode (2 files, 168 lines)
├── utils/          # Color utilities (2 files)
├── abilities/      # 7 unlockable abilities (2 files)
├── tools/          # ToolPolicy: command allowlist (1 file)
├── safety/         # Guardrails: path/shell/URL validation (1 file)
├── personality/    # 5-dimension trait engine (2 files)
├── events/         # Async EventBus + event dataclasses (3 files)
├── game/           # GrowthEngine: EXP/level/evolution (2 files)
├── runtime/        # TokenMeter (1 file)
├── logging/        # SensitiveDataFilter (1 file)
├── reserved/       # Stubs (superseded by focus/ + memory/) (4 files)
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
| Add memory feature | `memory/memory_service.py` | AI-driven extraction, structured memory into SQLite |
| Add user profile logic | `memory/user_profile_manager.py` | Identity extraction, profile updating |
| Add skill lifecycle | `skills/skill_manager.py` | SQLite-backed CRUD, workspace projection |
| Add focus mode | `focus/focus_companion.py` | Distraction-free work mode |
| Add color utility | `utils/color_utils.py` | Color math, palette generation |
| Add theme generation | `services/theme_generator.py` | Color extraction from images |

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
- `core/reserved/` stubs superseded by `focus/focus_companion.py` and `memory/` — DO NOT implement old stubs
- DB schema created on startup; no Alembic/migrations
- `pet_state_manager.py` and `time_format.py` are root-level core modules (not in subpackages)
- Sub-agents run in `multiprocessing.Process` with result-file IPC (see `agent/subagent_factory.py`)
- `core/memory/` (1,706 lines) and `core/skills/` (771 lines) are the largest subpackages (v5.2)
- `core/safety/`, `core/tools/`, `core/logging/`, `core/runtime/` use namespace packages (no `__init__.py`)
- Memory system uses FTS5 for full-text search on structured memories
- Skills are projected from SQLite to `/workspace/skills/SKILL.md` files
