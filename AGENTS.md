# LOBUDDY KNOWLEDGE BASE

**Generated:** 2026-05-03
**Commit:** 349317d
**Branch:** main

## OVERVIEW

PySide6 desktop pet AI assistant with SQLite persistence, nanobot integration, structured memory, skill lifecycle management, and EXP/leveling system. 163 Python files, ~20k lines (excl nanobot submodule).

## STRUCTURE

```
.
├── app/              # Bootstrap, config, entry points (5 files)
├── core/             # Domain logic (20 subpackages, 60+ modules)
│   ├── agent/        # AI boundary: adapter, gateway, sub-agents
│   ├── models/       # Pydantic domain models
│   ├── storage/      # SQLite repos, crypto
│   ├── tasks/        # TaskManager + TaskQueue
│   ├── game/         # GrowthEngine (EXP/level/evolution)
│   ├── personality/  # 5-dimension trait engine
│   ├── abilities/    # 7 unlockable abilities
│   ├── services/     # PetProgressService, PetAssetService, ThemeGenerator
│   ├── safety/       # Guardrails (path/shell/URL validation)
│   ├── tools/        # ToolPolicy (command allowlist)
│   ├── events/       # Async EventBus
│   ├── config/       # Pydantic Settings model
│   ├── logging/      # SensitiveDataFilter
│   ├── runtime/      # TokenMeter
│   ├── memory/       # Structured memory + user profile (v5.2)
│   ├── skills/       # Skill lifecycle management (v5.2)
│   ├── focus/        # Focus companion mode
│   ├── utils/        # Color utilities
│   └── reserved/     # Stubs (superseded by focus/ + memory/)
├── ui/               # PySide6 widgets (15 files + widgets/ + assets/)
├── tests/            # pytest suite (48 files, 345+ tests)
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
| Memory system | `core/memory/memory_service.py` | Structured memory extraction, inject, archive |
| User profile | `core/memory/user_profile_manager.py` | Identity extraction, profile updates |
| Skill lifecycle | `core/skills/skill_manager.py` | Create, patch, disable, archive skills |
| Focus mode | `core/focus/focus_companion.py` | Distraction-free work mode |
| Theme system | `core/services/theme_generator.py` | Color extraction, theme generation |
| Color utilities | `core/utils/color_utils.py` | Color math, palette operations |

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
| `MemoryService` | Class | `core/memory/memory_service.py` | Structured memory extraction, inject, archive |
| `SkillManager` | Class | `core/skills/skill_manager.py` | Skill lifecycle: create, patch, disable, archive |
| `FocusCompanion` | Class | `core/focus/focus_companion.py` | Distraction-free focus mode |

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
- Do NOT save secrets/API keys/tokens to structured memory (sanitized before storage)
- Do NOT skip image validation before analysis (magic bytes, size, format check mandatory)
- Do NOT bypass guardrails for tool argument validation (path/shell/URL)

### SECURITY

- Temp config files: 0o600 Unix / `icacls` ACL Windows — ACL failure deletes file + raises RuntimeError
- Secrets never logged: `SensitiveDataFilter` redacts API keys/bearer tokens from logs
- Memory sanitization: redacts `sk-`, `ghp_`, `xoxb-` tokens, bearer tokens, emails
- Command allowlist: only `ALLOWED_COMMANDS` set; blocks `iex`, `format`, `mkfs`, chaining operators, inline code via `-c`/`-enc`
- Path validation: null bytes, UNC, ADS, drive-relative, symlink escape all blocked
- URL validation: localhost, private IPs, non-standard ports, DNS rebinding blocked

## UNIQUE STYLES

- **Three-layer architecture:** `app/` (composition root) → `ui/` (presentation) → `core/` (domain)
- **Qt + asyncio coexistence:** AsyncWorker in QThread, `asyncio.run_coroutine_threadsafe()`
- **Hybrid persistence:** SQLite (core data) + JSON (appearance) + JSONL (workspace memory)
- **Process isolation:** Sub-agents run in `multiprocessing.Process` with result-file IPC
- **Reserved stubs:** `core/reserved/` contains placeholder interfaces for planned features
- **Chinese UI strings:** Default greetings, state labels, date formats are Chinese
- **AI-driven memory:** Chat analysis extracts structured memories (user profile, episodic, procedural) into SQLite with FTS5
- **Skill lifecycle:** Skills created via AI, stored in SQLite, projected to SKILL.md, with success/failure tracking and auto-maintenance

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
- `core/memory/` (1,706 lines) and `core/skills/` (771 lines) are the newest largest subpackages (v5.2)
- Two skills directories: `/skills/` (user-installed agent skills) and `/workspace/skills/` (nanobot workspace)
- `.env.example` documents 80+ configurable environment variables with Chinese comments
- `core/safety/`, `core/tools/`, `core/logging/`, `core/runtime/` use namespace packages (no `__init__.py`)
