# TEST KNOWLEDGE BASE

**Scope:** pytest test suite — 48 files, ~489 test functions across ~66 Test classes, flat directory structure

## STRUCTURE

```
tests/
├── test_pet.py                          # PetState, TaskRecord, TaskResult models
├── test_storage.py                      # Database, repositories, cascades
├── test_nanobot_adapter.py              # AI adapter, health checks, sessions
├── test_task_queue.py                   # FIFO queue, Qt signals
├── test_task_manager_session.py         # Task lifecycle, session attribution
├── test_event_bus.py                    # Async EventBus pub/sub
├── test_config_builder.py               # Temp config generation, ACL
├── test_security_fixes.py               # Guardrails, HTML sanitization, encryption
├── test_tool_policy.py                  # Shell policy, git safety
├── test_companion_features.py           # Time format, pet state, greetings (37 tests)
├── test_integration_phase1.py           # Guardrails, token accounting, abilities (28 tests)
├── test_image_validation.py             # Image magic bytes, size, format
├── test_image_analysis_integration.py   # End-to-end image analysis
├── test_analyze_image_tool.py           # nanobot tool integration
├── test_subagent_factory.py             # Multiprocessing sub-agents
├── test_shutdown_regression.py          # Exit reliability (subprocess-based)
├── test_exit_wiring.py                  # Source code pattern validation
├── test_bootstrap.py                    # Health checks, async bootstrap
├── test_ui_gif_support.py               # GIF animation, QApplication bootstrap
├── test_token_meter.py                  # Token counting
├── test_ability_persistence.py          # Ability unlock persistence
├── test_task_status_persistence.py      # Task status across restarts
├── test_image_upload.py                 # Image upload flow
├── test_temp_config_security.py         # Temp file ACL security
├── test_repair_4_28.py                  # Bug-fix regression tests
└── test_ui_redesign.py                  # UI redesign tests
```

## CONVENTIONS

- **No conftest.py:** All fixtures defined locally in each test file
- **Class-grouped:** Tests grouped into `Test<PascalCase>` classes with docstrings
- **Method naming:** `test_<subject>_<behavior>` with underscores
- **Local fixtures:** `@pytest.fixture` defined in file or class scope
- **monkeypatch:** Primary tool for env vars, singleton resets, module attribute replacement
- **tmp_path:** Pytest built-in for filesystem isolation
- **asyncio.run():** Most common async pattern (wraps async test in sync function)
- **Absolute imports:** `from core.models.pet import PetState` (never relative)
- **Minimal Settings:** `Settings(llm_api_key="test", ...)` as universal config constructor

## PySide6 MOCKING (CRITICAL)

Since tests run headless (no display), PySide6 must be mocked at module level:

```python
# Pattern A: sys.modules injection (preferred)
_pyside = type(sys)("PySide6")
_pyside.QtCore = type(sys)("QtCore")
_pyside.QtCore.QObject = _QObject
_pyside.QtCore.Signal = _Signal
sys.modules["PySide6"] = _pyside
sys.modules["PySide6.QtCore"] = _pyside.QtCore

# Pattern B: MagicMock injection
_pyside = MagicMock()
sys.modules["PySide6"] = _pyside
sys.modules["PySide6.QtCore"] = _pyside.QtCore

# Cleanup at bottom of file
for _mod in list(sys.modules.keys()):
    if _mod.startswith('PySide6'):
        del sys.modules[_mod]
```

## ASYNC TEST PATTERNS

```python
# Pattern A: asyncio_mode = "auto" with decorator
@pytest.mark.asyncio
async def test_health_check(self, monkeypatch):
    results = await health_check(settings)

# Pattern B: Manual asyncio.run() wrapper (most common)
def test_concurrent_add_tasks(self):
    async def run_test():
        results = await asyncio.gather(...)
    asyncio.run(run_test())

# Pattern C: @pytest.mark.anyio class marker
@pytest.mark.anyio
class TestAsyncFunctionality:
    async def test_health_check(self):
```

## ANTI-PATTERNS

- Do NOT create conftest.py (keep fixtures local)
- Do NOT use shared fixtures across files (each file is self-contained)
- Do NOT import PySide6 without mocking at module level
- Do NOT use `tempfile.mkdtemp()` when `tmp_path` fixture works
- Do NOT use relative imports in tests
- Do NOT skip PySide6 cleanup at file bottom

## COMMANDS

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_pet.py -v

# Run with coverage
pytest tests/ --cov=app --cov=core

# Run specific test class
pytest tests/test_storage.py::TestPetRepository -v

# Run specific test method
pytest tests/test_pet.py::TestPetState::test_add_exp_levels_up -v
```

## NOTES

- No shared test utilities — each file defines helpers locally
- Subagent tests use JSON test scripts injected via `LOBUDDY_SUBAGENT_TEST_SCRIPT` env var
- Subprocess-based tests for process-level behavior (shutdown, exit wiring)
- Source code inspection tests validate patterns without executing code
- Test suite grown from 28 files/345 tests to 48 files/~489 tests (v5.2)
