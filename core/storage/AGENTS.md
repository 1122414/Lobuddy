# STORAGE KNOWLEDGE BASE

**Scope:** SQLite persistence layer with repository pattern

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Database init | `db.py` | Singleton connection, schema |
| Chat/session | `chat_repo.py` | Messages, titles, history |
| Pet state | `pet_repo.py` | EXP, level, personality JSON |
| Tasks | `task_repo.py` | Queue, results |
| Settings | `settings_repo.py` | Runtime app settings |

## CONVENTIONS

- Repository pattern: one class per domain
- Singleton DB via `get_database()`
- JSON columns for complex types (personality)
- Context manager: `with self.db.get_connection() as conn`
- Manual commit after each operation

## ANTI-PATTERNS

- Do NOT use ORM (raw SQL preferred)
- Do NOT forget `conn.commit()`
- Do NOT store large blobs in SQLite

## NOTES

- No Alembic/migrations; schema created on startup
- `pet_repo` stores personality as JSON string
- `chat_repo` handles session titles and message counts
- `settings_repo` persists in SQLite (not config files)
