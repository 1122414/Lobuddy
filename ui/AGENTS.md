# UI KNOWLEDGE BASE

**Scope:** PySide6 widgets and user interface layer

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Main pet window | `pet_window.py` | Frameless, draggble, state display |
| Chat interface | `task_panel.py` | Session management, markdown |
| System tray | `system_tray.py` | Menu, notifications |
| Global hotkey | `hotkey_manager.py` | Worker thread, platform hooks |
| Popups | `result_popup.py` | Auto-closing status |
| Assets | `asset_manager.py` | Pet/tray visuals lookup |

## CONVENTIONS

- Frameless windows with `Qt.WindowType.FramelessWindowHint`
- Shadow effect via `QGraphicsDropShadowEffect`
- Monolithic widgets (not MVC/MVVM)
- Direct Qt signal/slot connections
- Inline CSS via `setStyleSheet()`

## ANTI-PATTERNS

- Do NOT block main thread (use workers for async)
- Do NOT create widgets without parent (memory leaks)
- Do NOT hardcode paths; use `asset_manager`

## NOTES

- `task_panel.py` is 318 lines (largest UI file)
- Chat sessions managed inline, not separate controller
- Markdown rendering via `markdown.Markdown(extensions=["nl2br"])`
