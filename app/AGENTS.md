# APP KNOWLEDGE BASE

**Scope:** Bootstrap, configuration, and entry points

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Main entry | `main.py` | Qt app, signal wiring, loops |
| Bootstrap | `bootstrap.py` | Config, logging, health checks |
| Health check | `health.py` | CLI dependency verification |
| Config schema | `config.py` | Pydantic settings, .env |

## CONVENTIONS

- `main.py` is composition root (wires all layers)
- Pydantic settings singleton via `get_settings()`
- `.env` file for local overrides
- Async worker thread for Qt + asyncio coexistence

## ANTI-PATTERNS

- Do NOT add business logic here (move to `core/`)
- Do NOT import UI in `config.py`
- Do NOT hardcode paths (use `workspace_path`, `data_dir`)

## NOTES

- Bootstrap creates directories: `workspace/`, `data/`, `logs/`
- Health check verifies: DB, nanobot, workspace
- Config loads from `.env` with `SettingsConfigDict`
- Entry split: runtime (`main.py`), init (`bootstrap.py`), CLI (`health.py`)
