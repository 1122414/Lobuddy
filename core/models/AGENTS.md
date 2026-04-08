# MODELS KNOWLEDGE BASE

**Scope:** Pydantic domain models

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Pet entity | `pet.py` | EXP, level, evolution, mood |
| Chat data | `chat.py` | Session, message schemas |
| Tasks | `task.py` | TaskRecord, TaskResult |
| Personality | `personality.py` | Trait engine, adjustments |
| Abilities | `ability.py` | Unlock system |

## CONVENTIONS

- Pydantic v2 `BaseModel`
- Datetime as `datetime` objects (not strings)
- JSON serialization via `.model_dump_json()`
- Validation in `model_validate_json()`

## ANTI-PATTERNS

- Do NOT use dicts for structured data (use models)
- Do NOT bypass Pydantic validation
- Do NOT store UI state in models

## NOTES

- `PetState` has computed properties: `get_exp_for_next_level()`
- Evolution stages as enum with Chinese names
- Personality traits stored as JSON in SQLite
