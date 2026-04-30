# LOBUDDY KNOWLEDGE BASE

**Generated:** 2026-04-29
**Commit:** 5cded67
**Branch:** main

## OVERVIEW

PySide6 desktop pet AI assistant with SQLite persistence, nanobot integration, and EXP/leveling system. 111 Python files, ~12k lines (excl nanobot submodule).

## STRUCTURE

```
.
├── app/              # Bootstrap, config, entry points (5 files)
├── core/             # Domain logic (14 subpackages, 30+ modules)
│   ├── agent/        # AI boundary: adapter, gateway, sub-agents
│   ├── models/       # Pydantic domain models
│   ├── storage/      # SQLite repos, crypto
│   ├── tasks/        # TaskManager + TaskQueue
│   ├── game/         # GrowthEngine (EXP/level/evolution)
│   ├── personality/  # 5-dimension trait engine
│   ├── abilities/    # 7 unlockable abilities
│   ├── services/     # PetProgressService, PetAssetService
│   ├── safety/       # Guardrails (path/shell/URL validation)
│   ├── tools/        # ToolPolicy (command allowlist)
│   ├── events/       # Async EventBus
│   ├── config/       # Pydantic Settings model
│   ├── logging/      # SensitiveDataFilter
│   ├── runtime/      # TokenMeter
│   └── reserved/     # Stubs: FocusCompanion, MemoryCardStore, MessageHighlight
├── ui/               # PySide6 widgets (13 files + widgets/)
├── tests/            # pytest suite (28 files, 345+ tests)
└── lib/nanobot/      # Vendored AI agent framework (git submodule)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new UI | `ui/` | Frameless widgets, direct Qt event handling |
| Database changes | `core/storage/` | Repository pattern, SQLite, no ORM |
| AI behavior | `core/agent/nanobot_adapter.py` | Single boundary to nanobot |
| Pet logic | `core/models/pet.py` | EXP, evolution, personality |
| Task lifecycle | `core/tasks/task_manager.py` | Central orchestrator |
| Config | `app/config.py` → `core/config/settings.py` | Pydantic + .env + DB overrides |
| Security | `core/safety/guardrails.py` | Path/shell/URL validation |
| Tool policy | `core/tools/tool_policy.py` | Command allowlist, git safety |
| Growth system | `core/game/growth.py` | EXP table, levels, evolution |
| Personality | `core/personality/personality_engine.py` | Keyword-based trait evolution |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `NanobotAdapter` | Class | `core/agent/nanobot_adapter.py` | AI boundary, temp config, session mgmt |
| `NanobotGateway` | Class | `core/agent/nanobot_gateway.py` | Stable facade over nanobot internals |
| `SubagentFactory` | Class | `core/agent/subagent_factory.py` | Multiprocessing sub-agent spawning |
| `TaskManager` | Class | `core/tasks/task_manager.py` | Task lifecycle orchestrator |
| `TaskQueue` | Class | `core/tasks/task_queue.py` | FIFO serial queue with Qt signals |
| `GrowthEngine` | Class | `core/game/growth.py` | EXP table, level-up, evolution |
| `PetState` | Model | `core/models/pet.py` | Pet entity with computed properties |
| `Database` | Class | `core/storage/db.py` | SQLite singleton, schema init |
| `SafetyGuardrails` | Class | `core/safety/guardrails.py` | Path/shell/URL validation |
| `ToolPolicy` | Class | `core/tools/tool_policy.py` | Command allowlist/blocklist |
| `EventBus` | Class | `core/events/bus.py` | Async pub/sub |
| `Settings` | Model | `core/config/settings.py` | Pydantic BaseSettings (80+ fields) |

## CONVENTIONS

- **Line length:** 100 chars (not 79) — enforced by black + ruff
- **Imports:** Absolute only (`from app...`, `from core...`, `from ui...`)
- **Config:** Env-driven via `.env`, Pydantic validation, DB override layer
- **Comments:** Short inline for business rules; Chinese in data strings, English in code
- **Tests:** Class-grouped, local fixtures, monkeypatch mocking, no conftest.py
- **Formatting:** black + ruff, mypy strict mode
- **Python:** >=3.11, targets py311/py312

## ANTI-PATTERNS (THIS PROJECT)

- Do NOT bypass `nanobot_adapter.py` for AI calls
- Do NOT reuse temp nanobot configs (always fresh, Windows ACL hardened)
- Do NOT use relative imports across app/core/ui
- Do NOT expose bridge outside localhost (security)
- Do NOT add business logic to `app/` (move to `core/`)
- Do NOT use ORM (raw SQL preferred in `core/storage/`)
- Do NOT block UI main thread (use workers for async)
- Do NOT store UI state in domain models

## UNIQUE STYLES

- **Three-layer architecture:** `app/` (composition root) → `ui/` (presentation) → `core/` (domain)
- **Qt + asyncio coexistence:** AsyncWorker in QThread, `asyncio.run_coroutine_threadsafe()`
- **Hybrid persistence:** SQLite (core data) + JSON (appearance) + JSONL (workspace memory)
- **Process isolation:** Sub-agents run in `multiprocessing.Process` with result-file IPC
- **Reserved stubs:** `core/reserved/` contains placeholder interfaces for planned features
- **Chinese UI strings:** Default greetings, state labels, date formats are Chinese

## COMMANDS

```bash
# Install
pip install -e lib/nanobot    # nanobot submodule first
pip install -e .              # then Lobuddy

# Run
python -m app.main            # desktop pet mode
lobuddy-health                # CLI health check

# Test
pytest tests/ -v
pytest tests/ --cov=app --cov=core

# Lint/format
ruff check .
black --check .
mypy app core ui
```

## NOTES

- Entry split: `app/main.py` (runtime) + `app/bootstrap.py` (init) + `app/health.py` (CLI)
- No CI at root; nanobot submodule has `.github/workflows/ci.yml`
- No conftest.py; all fixtures local to each test file
- PySide6 must be mocked at module level in tests (sys.modules injection)
- `core/tasks/` uses QObject/Signal — couples "pure core" to Qt
- DB schema created on startup; no Alembic/migrations
