# AGENT KNOWLEDGE BASE

**Scope:** AI boundary layer — nanobot integration, sub-agents, image analysis, token metering

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| AI task execution | `nanobot_adapter.py` | Single boundary to nanobot; temp config, session mgmt |
| Nanobot internals | `nanobot_gateway.py` | Stable facade over `_loop`, `_process_message` |
| Temp config builder | `config_builder.py` | Runtime JSON config with Windows ACL hardening |
| Sub-agent spawning | `subagent_factory.py` | `multiprocessing.Process` with result-file IPC |
| Sub-agent config | `subagent_spec.py` | Pydantic spec for sub-agent configuration |
| History compression | `history_compressor.py` | Summarize when token/turn thresholds exceeded |
| Image validation | `image_validation.py` | Magic bytes, size limits, format checks |
| Token metering | `token_meter_integration.py` | Records token usage per task |
| Image analysis tool | `tools/analyze_image_tool.py` | Custom nanobot tool for multimodal analysis |

## CONVENTIONS

- **Single boundary:** ALL AI calls go through `NanobotAdapter` — never directly to nanobot
- **Always-fresh configs:** Temp config files generated per-task, never cached
- **Windows ACL:** Temp config files get `icacls` restriction on Windows (API key protection)
- **Process isolation:** Sub-agents run in `multiprocessing.Process`, communicate via result files
- **Gateway pattern:** `NanobotGateway` wraps nanobot's internal `_loop` APIs for stability
- **History management:** `HistoryCompressor` triggers on token/turn thresholds, keeps recent messages

## ANTI-PATTERNS

- Do NOT bypass `NanobotAdapter` for AI calls
- Do NOT reuse temp nanobot configs (always fresh, always ACL-hardened)
- Do NOT call nanobot's internal `_loop` directly (use `NanobotGateway`)
- Do NOT spawn sub-agents without timeout (default 120s)
- Do NOT skip image validation before analysis (magic bytes, size, format)

## SECURITY

- Temp config files: 0o600 on Unix, icacls ACL on Windows
- API keys written to temp files, cleaned up after use
- Image validation: magic bytes, max 100MB, max 16384px dimensions
- SVG validation: must contain actual `<svg>` tag
- Sub-agent timeout: configurable (default 120s), force-kill on exceed

## NOTES

- `NanobotGateway` accesses nanobot's private `_loop` attribute — may break on nanobot updates
- `SubagentFactory._force_join_process()`: join(5s) → terminate() → join(5s) → kill() → join(5s)
- Token metering falls back to tiktoken estimation when nanobot doesn't report actual tokens
- Image compression: max 20 iterations, falls through to original on failure
- `tools/analyze_image_tool.py` is a custom nanobot `Tool` subclass
