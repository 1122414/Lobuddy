# Lobuddy 4.29.0 Start Plan

> Goal: make the existing companion/settings work reliable, readable, and shippable.
> This plan replaces the larger 4.29.0 draft with a version that matches the current codebase.

## 0. Current Reality

The project already has most of the foundation that the original plan asks for:

- `core.config.settings.Settings` is the canonical Pydantic settings model.
- `app.config` already loads `.env`, applies SQLite overrides, reloads settings, and can write managed keys back to `.env`.
- `core.storage.settings_repo.SettingsRepository` stores runtime settings, with encryption for API keys.
- `ui.settings_window.SettingsWindow` already has tabs for basic, appearance, theme, companion, and advanced settings.
- `ui.theme` already contains theme tokens, presets, a `ThemeManager`, and QSS helpers.
- `core.models.appearance.PetAppearance` and `core.services.pet_asset_service.PetAssetService` already handle pet image/GIF customization.
- `core.pet_state_manager.PetStateManager` already models idle/listening/thinking/working/happy/sleepy/error.
- `core.reserved.memory_card_store`, `message_highlight`, and `focus_companion` are intentionally stubbed/reserved.

Because of this, 4.29.0 should not introduce a new `ConfigManager`, a parallel `user_settings.json`, or a large new folder hierarchy. The safer path is to repair and consolidate the current implementation.

## 1. Product Target

Version name:

```text
Lobuddy 4.29.0 - Companion Settings Stabilization
```

Primary outcome:

- The pet UI feels stable and compact.
- Settings are understandable and persist correctly.
- Theme, pet appearance, clock, chat time display, and companion toggles work from the existing settings window.
- AI/API errors are shown in user-friendly language.
- Reserved features stay visibly scoped and do not become half-built systems.

## 2. Non-Goals

Do not do these in 4.29.0:

- Do not add a new config system beside `Settings`, `SettingsRepository`, and `.env`.
- Do not move app modules into a new `app/ui`, `app/core`, or similar tree.
- Do not implement vector memory, automatic memory extraction, calendar integration, browser automation, or full focus statistics.
- Do not redesign nanobot internals or bypass `core.agent.nanobot_adapter`.
- Do not add new dependencies unless an existing testable gap truly requires one.
- Do not expose local bridge/network functionality beyond localhost.

## 3. Implementation Strategy

Use the existing architecture:

- Pydantic schema: `core/config/settings.py`
- Runtime overrides: `core/storage/settings_repo.py`
- Settings load/save boundary: `app/config.py`
- Settings UI: `ui/settings_window.py`
- Pet layout and interaction: `ui/pet_window.py`, `ui/quick_action_menu.py`
- Chat panel: `ui/task_panel.py`
- Task status card: `ui/task_card_panel.py`
- Theme tokens: `ui/theme.py`
- Pet assets: `core/models/appearance.py`, `core/services/pet_asset_service.py`, `ui/asset_manager.py`
- AI result/error boundary: `core/agent/nanobot_adapter.py`

## 4. Phase 0 - Encoding And Text Cleanup

Problem:

Several UI strings and setting defaults are garbled. This affects the settings window, pet status text, task card buttons, and chat panel labels.

Scope:

- Replace garbled text with readable Chinese or simple English.
- Prefer short product-facing Chinese labels.
- Keep internal keys unchanged.
- Do not alter logic while doing text cleanup.

Files:

- `core/config/settings.py`
- `ui/settings_window.py`
- `ui/task_panel.py`
- `ui/task_card_panel.py`
- `ui/pet_window.py`
- `app/main.py` where user-facing startup or placeholder text appears

Acceptance:

- Main pet widget, chat panel, settings window, and task card show readable labels.
- `python -m py_compile` passes for touched files.
- Existing tests that do not require unavailable dependencies still collect.

## 5. Phase 1 - Settings Persistence Baseline

Problem:

Settings currently flow through both SQLite overrides and `.env` writes. That can work, but the behavior must be explicit and tested.

Decision:

Keep the current priority:

```text
.env / environment defaults -> SQLite runtime overrides -> Settings instance
```

Keep `save_settings_to_env()` only as a compatibility/export step. The primary runtime source after the first save is SQLite through `SettingsRepository`.

Tasks:

1. Deduplicate `field_map` in `app.config.apply_db_overrides`.
2. Add missing settings fields that already exist in `Settings` but are not loaded from DB, such as:
   - `pet_clock_hover_full_format`
   - `conversation_timeline_min_dot_gap_px`
   - reserved toggles only if shown in UI
3. Normalize bool parsing in DB overrides. Accept at least `true`, `1`, `yes`, `on`; treat `false`, `0`, `no`, `off` as false.
4. Ensure settings saved from `SettingsWindow` are present in both DB and managed `.env` output when intended.
5. Preserve API key encryption in `SettingsRepository`; do not store raw API keys in SQLite.

Acceptance:

- Changing pet name, theme preset, pet clock, chat time display, and shell toggle persists after `reload_settings()`.
- API key round-trips through `SettingsRepository` and is encrypted at rest.
- No duplicate mapping entries in `app.config`.

Suggested tests:

- `tests/test_config_builder.py`
- `tests/test_security_fixes.py`
- Add focused tests for `apply_db_overrides` bool parsing.

## 6. Phase 2 - Settings Window Usability

Problem:

The current settings window already has the right tabs, but many labels are garbled and some controls are too low-level or unclear.

Keep the existing tab structure:

- Basic
- Appearance
- Theme
- Companion
- Advanced

Tasks:

1. Rename tabs and labels:
   - Basic -> 基础
   - Appearance -> 外观
   - Theme -> 主题
   - Companion -> 陪伴
   - Advanced -> 高级
2. Keep Advanced as the only place for API Key, Base URL, Model, Timeout, and Shell.
3. Add clear helper text for API settings:
   - API Key is required for AI chat.
   - Multimodal/image model is optional unless image analysis is used.
4. Keep custom pet asset upload/reset in Appearance.
5. Keep theme preset and custom colors in Theme.
6. Do not add new pages until existing tabs are readable and stable.

Acceptance:

- A non-developer can identify where to change pet name, avatar, theme, clock, chat time, and AI config.
- Save/cancel behavior remains unchanged.
- Settings window does not write invalid empty model/base URL values.

## 7. Phase 3 - Pet Widget Stability

Problem:

Recent UI work exposed layout issues in the compact pet widget: status text, speech bubble, pet image, EXP bar, and clock can overlap or compress.

Tasks:

1. Treat the top orange status bubble as the only normal pet speech/status display.
2. Keep click feedback from creating a second white speech bubble unless explicitly re-enabled later.
3. Keep pet image, pet name, EXP bar, level text, and clock inside fixed responsive bounds.
4. Level text should live inside the EXP bar.
5. Clock must have enough width for `MM/dd HH:mm`.
6. Use stable fixed dimensions for the widget at default scale; apply `PetAppearance.scale` consistently.

Files:

- `ui/pet_window.py`
- `core/pet_state_manager.py`
- `core/time_format.py`

Acceptance:

- Clicking the pet does not shift the pet image upward.
- Top status text does not overlap the pet image.
- EXP bar and clock do not overlap at default scale.
- Pet widget remains usable at 0.5x, 1.0x, and 2.0x scale.

## 8. Phase 4 - Task Card Scope

Problem:

`TaskCardPanel` includes buttons for screenshot and open web, but `app/main.py` currently wires them to placeholders. This makes the UI look like it supports features that do not exist.

Decision:

For 4.29.0, the task card is a task status card, not a browser automation panel.

Tasks:

1. Remove or hide screenshot/open-web buttons by default.
2. Keep:
   - title
   - status
   - short result
   - optional details
   - continue/close
   - EXP reward on completion
3. Only show future action buttons if the `TaskCardModel` explicitly declares available actions.

Acceptance:

- Running task card only shows truthful controls.
- No placeholder action appears in normal UI.
- Task card still appears on task start and completion.

## 9. Phase 5 - Friendly AI Errors

Problem:

Raw API/provider errors can leak into chat or task summaries. `NanobotAdapter._looks_like_api_error()` already detects common signatures, but the UI still needs a clear presentation.

Tasks:

1. Keep detection in `core.agent.nanobot_adapter`.
2. Convert known API errors into short user-facing summaries:
   - missing API key
   - invalid API key
   - rate limit
   - server unavailable
   - timeout
3. In chat/task UI, show:
   - what happened
   - likely fix
   - button or instruction to open Settings
4. Keep raw details in logs or details view, not as the main message.

Acceptance:

- Missing API key produces a friendly message and points to Advanced settings.
- Invalid base URL/model does not appear as a raw JSON blob in the main chat bubble.
- Sensitive tokens are not shown in UI or logs.

## 10. Phase 6 - Reserved Features Stay Reserved

Existing reserved modules:

- `core/reserved/memory_card_store.py`
- `core/reserved/message_highlight.py`
- `core/reserved/focus_companion.py`

Decision:

Do not expand these into full features in 4.29.0. They can be surfaced only as disabled/experimental toggles if needed.

Allowed:

- Manual memory card CRUD backed by SQLite only if there is a direct UI need.
- A simple local focus timer only if it does not touch notifications/calendar/statistics.

Not allowed:

- Vector database.
- Automatic long-term memory extraction.
- Calendar integration.
- OS notification scheduling.
- AI mode manager with tool confirmation redesign.

## 11. Suggested Milestones

### Milestone A - Text And Layout Patch

Files:

- `ui/pet_window.py`
- `ui/task_card_panel.py`
- `ui/settings_window.py`
- `core/config/settings.py`

Deliverables:

- Readable UI labels.
- Stable compact pet widget.
- Task card no longer exposes fake buttons.

Verification:

```bash
python -m py_compile ui/pet_window.py ui/task_card_panel.py ui/settings_window.py core/config/settings.py
```

### Milestone B - Settings Persistence Patch

Files:

- `app/config.py`
- `core/storage/settings_repo.py`
- `tests/test_security_fixes.py`
- new focused settings override tests

Deliverables:

- DB override field map is complete and deduplicated.
- Bool parsing is robust.
- API key storage remains encrypted.

Verification:

```bash
pytest tests/test_security_fixes.py -q
pytest tests/test_config_builder.py -q
```

### Milestone C - User-Friendly Errors

Files:

- `core/agent/nanobot_adapter.py`
- `ui/task_panel.py`
- `ui/task_card_panel.py`

Deliverables:

- Friendly API/key/timeout errors.
- Raw provider details hidden from main user copy.

Verification:

```bash
pytest tests/test_nanobot_adapter.py -q
pytest tests/test_nanobot_adapter_timeout.py -q
```

## 12. Test Environment Prerequisite

Before trusting full-suite results, install/use an environment with:

- Python 3.11+
- `pydantic>=2`
- `pydantic-settings`
- `loguru`
- `PySide6`
- `Pillow`
- `pytest`
- `pytest-asyncio`

The current local environment may fail collection if it has Pydantic v1 or lacks UI/image dependencies. Record those as environment failures, not product regressions.

## 13. Definition Of Done

4.29.0 is done when:

- Pet widget has no overlapping text/image/EXP/clock at default scale.
- Settings window labels are readable.
- Pet name, theme, avatar, clock, chat time, and AI settings persist after restart.
- Task card only exposes implemented actions.
- Missing/invalid API configuration is presented clearly.
- Existing nanobot boundary remains untouched.
- No new config architecture is introduced.
- Focus/memory/highlight remain scoped unless implemented as small, local, manually-triggered features.

