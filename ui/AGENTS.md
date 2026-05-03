# UI KNOWLEDGE BASE

**Scope:** PySide6 widgets and user interface layer — 15 .py files, ~4,200 lines

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Main pet window | `pet_window.py` (558 lines) | Frameless, draggable, GIF states |
| Chat interface | `task_panel.py` (643 lines) | Session management, markdown, task cards |
| Settings window | `settings_window.py` (978 lines) | Largest file — all settings panels |
| Skill panel | `skill_panel.py` | Skill management UI |
| History window | `history_window.py` | Conversation timeline |
| Theme editor | `theme_editor.py` | Color picker, preset editor |
| Theme engine | `theme.py` (559 lines) | Dynamic theming, CSS generation |
| Styles | `styles.py` | Reusable Qt stylesheets |
| Task cards | `task_card_panel.py` | Active task display cards |
| System tray | `system_tray.py` | Menu, notifications |
| Global hotkey | `hotkey_manager.py` | Worker thread, platform hooks |
| Asset manager | `asset_manager.py` | Pet/tray visuals lookup |
| Pet settings | `pet_settings_panel.py` | Pet appearance config |
| Quick actions | `quick_action_menu.py` | Pet interaction menu |
| Widgets | `widgets/` | Reusable components (conversation_timeline) |
| Assets | `assets/` | GIF/PNG sprites and icons |

## CONVENTIONS

- Frameless windows with `Qt.WindowType.FramelessWindowHint`
- Shadow effect via `QGraphicsDropShadowEffect`
- Monolithic widgets (not MVC/MVVM)
- Direct Qt signal/slot connections
- Inline CSS via `setStyleSheet()`; dynamic theming via `theme.py`
- Theme uses QPalette + stylesheet combo approach

## ANTI-PATTERNS

- Do NOT block main thread (use workers for async)
- Do NOT create widgets without parent (memory leaks)
- Do NOT hardcode paths; use `asset_manager`
- Do NOT hardcode colors; use theme system

## NOTES

- `settings_window.py` (978 lines) is the largest file — contains all settings panels inline
- `task_panel.py` (643 lines) grew from 318 with task card and timeline features
- `theme.py` (559 lines) handles dynamic palette + stylesheet generation
- Markdown rendering via `markdown.Markdown(extensions=["nl2br"])`
- Two separate skill views: `skill_panel.py` (UI) mirrors `core/skills/skill_manager.py` (backend)
