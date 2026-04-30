# Lobuddy 4.29.1 Start Plan

> Goal: turn the large 4.29.1 companion-core draft into an implementation plan that matches the current repository.
> This version is intentionally conservative: build the smallest real USER.md memory loop first, then ship local focus mode and a skill panel MVP.

## 0. Current Reality

The 4.29.1 plan targets three features:

- AI-maintained user profile memory in `data/memory/USER.md`.
- Local focus companion / Pomodoro mode.
- A "what I can do" skill panel.

The current codebase already provides useful foundations:

- `core.config.settings.Settings` is still the canonical settings model.
- `app.config` already applies SQLite runtime overrides through `SettingsRepository`.
- `core.storage.chat_repo.ChatRepository` persists chat sessions and messages.
- `core.agent.nanobot_adapter.NanobotAdapter` is the AI boundary and already owns prompt execution, session keys, history compression, token tracking, temporary config handling, and guardrails.
- `ui.task_panel.TaskPanel` already has chat UI, message timestamps, a right-side conversation timeline, image upload, and a small hard-coded skill button.
- `ui.settings_window.SettingsWindow` already has a companion settings tab for greeting, pet click feedback, clock, pet state, chat time, and timeline options.
- `core.reserved.focus_companion`, `core.reserved.memory_card_store`, and `core.reserved.message_highlight` exist as small reserved stubs.

But the 4.29.1 target is not implemented yet:

- There is no `core/memory/` package.
- `data/memory/USER.md` does not exist.
- No profile patch schema, trigger rules, profile compaction, or prompt injection exists.
- Focus mode exists only as a reserved in-memory stub; there is no timer lifecycle, pet-state link, or UI control.
- The skill panel is only a hard-coded chat message, not a registry-backed panel with click-to-fill prompts.
- Settings contain only the earlier reserved focus fields; they do not contain the memory profile or skill panel flags from the 4.29.1 plan.
- Test execution in the current local shells is blocked by dependency/environment mismatch: default Python has Pydantic v1, and the `dp-cli` env is missing `pydantic_settings`.

Therefore 4.29.1 should not start by adding a large framework. It should first make a narrow, testable memory pipeline, then layer the focus and skill UI on top.

## 1. Product Target

Version name:

```text
Lobuddy 4.29.1 - Companion Core MVP
```

Primary outcome:

- Lobuddy can maintain a local `USER.md` profile safely over time.
- AI replies can receive a compact user-profile context when the feature is enabled.
- Focus mode can start, stop, complete, and reflect its state in the pet UI.
- Users can open a skill panel, inspect available abilities, and click a skill example into the input box.

## 2. Non-Goals

Do not do these in 4.29.1:

- Do not implement vector memory, embeddings, RAG memory, or a memory review inbox.
- Do not let the model rewrite the whole `USER.md` file directly.
- Do not store API keys, tokens, local secrets, or raw private paths in `USER.md`.
- Do not build message highlight/bookmarking; the original 4.29.1 plan explicitly excludes it.
- Do not implement calendar integration, OS notifications, focus statistics, or focus history beyond the current session.
- Do not execute skills from the skill panel. The 4.29.1 panel is explanatory and prompt-filling only.
- Do not bypass `core.agent.nanobot_adapter` for AI calls.
- Do not add a second settings system or `user_settings.json`.

## 3. Implementation Strategy

Use the existing architecture:

- Settings schema: `core/config/settings.py`
- Env and DB setting flow: `app/config.py`, `core/storage/settings_repo.py`
- Chat history source: `core/storage/chat_repo.py`, `core/models/chat.py`
- AI boundary: `core/agent/nanobot_adapter.py`
- Runtime orchestration: `app/main.py`, `core/tasks/task_manager.py`
- UI surfaces: `ui/settings_window.py`, `ui/task_panel.py`, `ui/pet_window.py`
- Reserved compatibility: keep `core/reserved/*` importable, but promote real 4.29.1 behavior into clearer modules when useful.

Recommended new modules:

```text
core/memory/user_profile_schema.py
core/memory/user_profile_manager.py
core/memory/user_profile_triggers.py
core/memory/user_profile_prompts.py
core/focus/focus_companion.py
core/skills/skill_registry.py
ui/skill_panel.py
tests/test_user_profile_manager.py
tests/test_user_profile_patch.py
tests/test_user_profile_triggers.py
tests/test_focus_companion.py
tests/test_skill_registry.py
```

If adding `core/focus/` feels too large, `core/services/focus_companion_service.py` is acceptable. Avoid expanding `core/reserved/` into the permanent home for real logic.

## 4. Phase 0 - Readiness And Guardrails

Problem:

The repo has enough foundation for 4.29.1, but the local test environment is not currently reliable and several user-facing strings are garbled. 4.29.1 should not spread new settings or UI text before the baseline is understandable.

Scope:

- Confirm the intended Python environment has `pydantic>=2`, `pydantic-settings`, `PySide6`, `pytest`, and `pytest-asyncio`.
- Keep any text cleanup small and limited to files touched by 4.29.1.
- Do not perform a broad UI rewrite in this phase.
- Add no memory/focus behavior yet.

Acceptance:

- `python -m py_compile` passes for touched files.
- The chosen test command can import `app.config` and `core.config.settings`.
- New 4.29.1 strings are readable UTF-8 and do not add more mojibake.

Suggested commands:

```bash
python -m py_compile app/config.py core/config/settings.py
python -m pytest -q tests/test_config_overrides.py
```

## 5. Phase 1 - Settings Contract

Problem:

The plan defines memory, focus, and skill panel flags, but the current `Settings` model and `.env` mapping only contain earlier companion fields and a small reserved focus subset.

Scope:

- Add memory profile settings to `core/config/settings.py`.
- Add skill panel settings to `core/config/settings.py`.
- Extend focus settings only to the MVP fields needed by 4.29.1.
- Add every new setting to `app.config._ENV_VAR_MAP`.
- Persist new settings through `SettingsRepository` where UI changes exist.
- Expose only the most important toggles in `SettingsWindow`: memory profile enabled, memory injection enabled, focus mode enabled, and skill panel enabled.

Initial settings:

```env
MEMORY_PROFILE_ENABLED=true
MEMORY_PROFILE_FILE=data/memory/USER.md
MEMORY_PROFILE_INJECT_ENABLED=true
MEMORY_PROFILE_MAX_INJECT_CHARS=2000
MEMORY_PROFILE_UPDATE_EVERY_N_USER_MESSAGES=6
MEMORY_PROFILE_UPDATE_ON_SESSION_END=true
MEMORY_PROFILE_UPDATE_ON_STRONG_SIGNAL=true
MEMORY_PROFILE_DAILY_CONSOLIDATION=false
MEMORY_PROFILE_MAX_RECENT_MESSAGES=30
MEMORY_PROFILE_MAX_PATCH_ITEMS=8
MEMORY_PROFILE_REQUIRE_HIGH_CONFIDENCE=true
MEMORY_PROFILE_MIN_CONFIDENCE=0.75
MEMORY_PROFILE_SHOW_UPDATE_NOTICE=true

FOCUS_MODE_ENABLED=false
FOCUS_DEFAULT_MINUTES=25
FOCUS_BREAK_MINUTES=5
FOCUS_END_REMINDER_ENABLED=true
FOCUS_BREAK_END_REMINDER_ENABLED=true
FOCUS_MUTE_GREETING=true
FOCUS_STATUS_TEXT=Focusing
FOCUS_AUTO_LOOP=false

SKILL_PANEL_ENABLED=true
SKILL_PANEL_SHOW_EXAMPLES=true
SKILL_PANEL_CLICK_TO_FILL_INPUT=true
SKILL_PANEL_SHOW_PERMISSION_BADGE=true
```

Acceptance:

- New settings instantiate with defaults.
- DB overrides can coerce bool, int, path, and string values.
- Settings UI can save and reload the visible 4.29.1 toggles.
- No API key or token setting is copied into memory profile settings.

## 6. Phase 2 - USER.md Manager Without LLM

Problem:

The most important new feature is local profile memory. It needs deterministic file creation, parsing, validation, patching, and compaction before any AI update loop is added.

Scope:

- Create `core/memory/user_profile_schema.py`.
- Create `core/memory/user_profile_manager.py`.
- Create `core/memory/user_profile_triggers.py`.
- Create `core/memory/user_profile_prompts.py` with prompt strings only.
- Create `data/memory/USER.md` lazily at runtime, not as a committed personal file.
- Implement patch application without calling the LLM.

Required manager API:

```text
ensure_profile_file()
load_profile()
save_profile()
build_default_profile()
apply_patch()
compact_profile_for_prompt()
get_profile_sections()
```

Required patch rules:

- Only allow known section names.
- Support `add`, `update`, `remove`, and `uncertain`.
- Reject or quarantine low-confidence items when high confidence is required.
- Redact likely secrets before writing.
- Keep file writes atomic.
- Never replace the whole file from model output.

Suggested `USER.md` sections:

```md
# USER.md

## Basic Notes
- No stable notes yet.

## Preferences
- No stable notes yet.

## Work And Projects
- No stable notes yet.

## Communication Style
- No stable notes yet.

## Long-Term Goals
- No stable notes yet.

## Boundaries And Dislikes
- No stable notes yet.

## Open Questions
- No stable notes yet.
```

Acceptance:

- A missing profile file is created with stable sections.
- A valid patch updates only the targeted section.
- Unknown sections are rejected.
- Secret-like strings are not persisted.
- `compact_profile_for_prompt()` returns bounded text under `MEMORY_PROFILE_MAX_INJECT_CHARS`.

## 7. Phase 3 - AI Profile Update And Injection

Problem:

Once local profile handling is safe, Lobuddy can ask the model for profile patches and inject compact profile context into replies.

Scope:

- Add trigger checks based on user message count, session end, and strong memory signals.
- Use recent chat messages from `ChatRepository`.
- Build a profile-update prompt that requests JSON patch output only.
- Route any LLM interaction through `NanobotAdapter` or a narrow helper owned by the adapter boundary.
- Apply the patch through `UserProfileManager.apply_patch()`.
- Inject compact profile context before normal task execution when enabled.

Strong signal examples:

```text
remember this
from now on
I do not like
I like
default to
remember that
```

Integration options:

- Preferred: add a small `UserProfileService` used from `app/main.py` around persisted chat messages and task completion.
- Acceptable: add a profile context hook inside `NanobotAdapter.run_task()` if it stays small and testable.

Acceptance:

- Normal chat still works when memory is disabled.
- When injection is enabled, prompts receive compact profile context.
- A strong signal can produce a validated patch.
- Bad JSON or unsafe patch output is ignored without breaking the user request.
- Update notices are shown only when `MEMORY_PROFILE_SHOW_UPDATE_NOTICE` is true.

## 8. Phase 4 - Focus Companion MVP

Problem:

Focus mode is currently a reserved in-memory stub. 4.29.1 should make it usable without building a full productivity system.

Scope:

- Add a real focus session model with states: idle, focusing, break, completed, stopped.
- Use a Qt timer in UI or a small core timer service that can be driven by UI.
- Add start/stop controls in `TaskPanel` or the pet quick menu.
- Link focus state to pet status text through `PetWindow.set_pet_state_override()`.
- Respect `FOCUS_MUTE_GREETING`.
- Keep session history/statistics out of scope.

Acceptance:

- User can start a default 25-minute focus session.
- User can stop the session.
- When focus is active, pet status displays the configured focus text.
- At focus completion, the app can enter break state or stop based on `FOCUS_AUTO_LOOP`.
- The feature is fully disabled when `FOCUS_MODE_ENABLED=false`.

## 9. Phase 5 - Skill Panel MVP

Problem:

`TaskPanel._on_show_skills()` currently emits a hard-coded message. The 4.29.1 plan needs a visible capability boundary and click-to-fill prompts.

Scope:

- Add a small `SkillDefinition` schema.
- Add a local `SkillRegistry` with built-in Lobuddy abilities.
- Add `ui/skill_panel.py` as a lightweight dialog or slide-out panel.
- Wire the existing skill button to the panel.
- When enabled, clicking an example fills `TaskPanel.input_box`.
- Permission badges are labels only; do not execute or install skills.

Initial skills:

- Chat and reasoning
- Codebase help
- Image analysis when image model is configured
- Task execution through nanobot tools
- Desktop pet companion controls

Acceptance:

- Skill panel opens from the existing chat panel.
- Disabled skills are visibly marked.
- Clicking an example prompt fills the input box when configured.
- Skill registry is unit-tested without PySide6.

## 10. Phase 6 - Integration Polish

Problem:

The three MVPs need to feel coherent without growing into a rewrite.

Scope:

- Add small settings UI sections for Memory, Focus, and Skills.
- Keep labels concise and readable.
- Keep business logic out of UI files where possible.
- Ensure memory updates, focus state, and skill-panel actions do not block the Qt main thread.
- Add graceful failure messages for memory-update errors.

Acceptance:

- All 4.29.1 toggles are discoverable.
- Turning a toggle off actually disables the feature.
- No feature creates noisy chat messages by default.
- Existing chat, image upload, timeline, and settings persistence continue to work.

## 11. Test Plan

Unit tests:

```bash
pytest tests/test_user_profile_manager.py -q
pytest tests/test_user_profile_patch.py -q
pytest tests/test_user_profile_triggers.py -q
pytest tests/test_focus_companion.py -q
pytest tests/test_skill_registry.py -q
pytest tests/test_config_overrides.py -q
```

Integration/smoke tests:

```bash
pytest tests/test_nanobot_adapter.py -q
pytest tests/test_companion_features.py -q
python -m py_compile app/config.py core/config/settings.py core/agent/nanobot_adapter.py
```

Manual checks:

- Start app.
- Open settings and toggle Memory, Focus, and Skill Panel options.
- Send a normal chat message with memory disabled.
- Enable memory and send a strong signal message.
- Confirm `data/memory/USER.md` is created and updated safely.
- Start and stop focus mode.
- Open skill panel and click an example prompt.

## 12. Definition Of Done

4.29.1 is done when:

- `data/memory/USER.md` is created on demand.
- Profile patches are schema-validated and applied safely.
- Secret-like content is redacted or rejected before writing.
- Compact profile context can be injected into AI prompts behind a setting flag.
- Memory update triggers work for message count and strong signals.
- Focus mode can start, stop, complete, and update pet status.
- Skill panel is registry-backed and supports click-to-fill examples.
- All new features have settings flags and DB override support.
- The new unit tests pass in the intended Python environment.
- Existing AI execution still routes through `NanobotAdapter`.

## 13. Recommended Build Order

1. Fix/test the Python environment and add settings fields.
2. Build deterministic `UserProfileManager`.
3. Add patch schema and tests.
4. Add compact injection into AI calls.
5. Add AI patch generation behind trigger rules.
6. Ship focus MVP.
7. Replace hard-coded skill text with registry-backed skill panel.
8. Polish settings UI and manual smoke test.

This order keeps the highest-risk feature, memory writes, under deterministic tests before any model output is allowed near `USER.md`.
