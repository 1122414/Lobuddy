# LOBUDDY KNOWLEDGE BASE

**Generated:** 2026-04-06

## OVERVIEW

PySide6 desktop pet AI assistant with SQLite persistence, nanobot integration, and EXP/leveling system.

## STRUCTURE

```
.
├── app/              # Bootstrap, config, main entry
├── core/             # Domain logic (storage, models, tasks, agent)
├── ui/               # PySide6 widgets (pet window, chat panel)
├── tests/            # pytest test suite
└── lib/nanobot/      # Vendored AI agent framework (submodule)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new UI | `ui/` | Frameless widgets, direct Qt event handling |
| Database changes | `core/storage/` | Repository pattern, SQLite |
| AI behavior | `core/agent/nanobot_adapter.py` | Single boundary to nanobot |
| Pet logic | `core/models/pet.py` | EXP, evolution, personality |
| Task lifecycle | `core/tasks/task_manager.py` | Central orchestrator |
| Config | `app/config.py` | Pydantic + .env |

## CONVENTIONS

- **Line length:** 100 chars (not 79)
- **Imports:** Absolute only (`from app...`, `from core...`)
- **Config:** Env-driven via `.env`, Pydantic validation
- **Comments:** Short inline for business rules, mixed EN/CN
- **Tests:** Class-grouped, local fixtures, monkeypatch mocking

## ANTI-PATTERNS

- Do NOT bypass `nanobot_adapter.py` for AI calls
- Do NOT reuse temp nanobot configs (always fresh)
- Do NOT use relative imports across app/core/ui
- Do NOT expose bridge outside localhost (security)

## COMMANDS

```bash
# Install
pip install -e .
pip install -e lib/nanobot

# Run
python -m app.main

# Test
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov=core
```

## NOTES

- Entry split: `app/main.py` + `app/bootstrap.py` + `app/health.py`
- Hybrid persistence: SQLite (core data) + JSONL (workspace memory)
- Nanobot config generated at runtime to temp dir
- No CI at root; nanobot submodule has `.github/workflows/ci.yml`
