"""AgentTracingHook — nanobot AgentHook that traces AI calls, tool invocations, and responses.

Plug into nanobot.run(prompt, hooks=[..., AgentTracingHook()]) to trace:
- Before each LLM iteration (messages, iteration count)
- Tool calls (name, arguments, guardrail status)
- After each iteration (tokens used, stop reason, errors)
- Final content generation
"""

import time
from typing import Any

from core.logging.trace import get_logger

agent_log = get_logger("agent")
tool_log = get_logger("tool")


class AgentTracingHook:
    """Traces nanobot agent lifecycle events for full-chain observability.

    Implements the AgentHook protocol. Each hook method logs structured
    information about the current iteration: messages, tool calls, token
    usage, stream activity, and errors.

    Must be used with set_trace_id(task_id) set beforehand so all entries
    share the same correlation ID.
    """

    _properties_set = {"_iteration_start", "_tool_start", "_total_tool_calls"}

    def __init__(self) -> None:
        self._clear_state()

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") and name not in self._properties_set:
            pass
        super().__setattr__(name, value)

    def _clear_state(self) -> None:
        self._iteration_start: float = 0.0
        self._tool_start: float = 0.0
        self._total_tool_calls: int = 0

    def wants_streaming(self) -> bool:
        return False

    async def before_iteration(self, ctx: Any) -> None:
        msg_count = len(ctx.messages) if ctx.messages else 0
        self._iteration_start = time.monotonic()
        agent_log.info(
            "Agent iteration #%d — messages=%d, has_response=%s",
            ctx.iteration,
            msg_count,
            ctx.response is not None,
        )

    async def on_stream(self, ctx: Any, delta: str) -> None:
        pass

    async def on_stream_end(self, ctx: Any, *, resuming: bool = False) -> None:
        agent_log.debug(
            "Stream ended (resuming=%s, iteration=%d)", resuming, ctx.iteration
        )

    async def before_execute_tools(self, ctx: Any) -> None:
        if not ctx.tool_calls:
            return

        self._tool_start = time.monotonic()
        for tc in ctx.tool_calls:
            tc_name = getattr(tc, "name", "unknown")
            tc_args = getattr(tc, "arguments", {})
            args_summary = self._summarize_args(tc_args)
            self._total_tool_calls += 1
            tool_log.info(
                "Tool call #%d — %s(%s)",
                self._total_tool_calls,
                tc_name,
                args_summary,
            )

    async def after_iteration(self, ctx: Any) -> None:
        elapsed = (time.monotonic() - self._iteration_start) * 1000
        usage = getattr(ctx, "usage", {}) or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        agent_log.info(
            "Agent iteration #%d done — %.0fms, tokens: prompt=%d completion=%d total=%d, "
            "stop_reason=%s, error=%s",
            ctx.iteration,
            elapsed,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            getattr(ctx, "stop_reason", None) or "none",
            "yes" if getattr(ctx, "error", None) else "no",
        )

        tool_events = getattr(ctx, "tool_events", []) or []
        if tool_events:
            for te in tool_events:
                tool_name = getattr(te, "name", str(te)) if not isinstance(te, dict) else te.get("name", "?")
                tool_status = getattr(te, "status", "?") if not isinstance(te, dict) else te.get("status", "?")
                tool_log.info("Tool result — %s: %s", tool_name, tool_status)

    def finalize_content(self, ctx: Any, content: str | None) -> str | None:
        agent_log.info(
            "Agent final content — length=%d, preview=%s",
            len(content) if content else 0,
            self._truncate(content, 120),
        )
        self._clear_state()
        return content

    @staticmethod
    def _summarize_args(args: Any) -> str:
        if not args:
            return ""
        if isinstance(args, dict):
            parts = []
            for k, v in args.items():
                v_str = str(v)
                if len(v_str) > 60:
                    v_str = v_str[:57] + "..."
                parts.append(f"{k}={v_str}")
            return ", ".join(parts[:5])
        v_str = str(args)
        return v_str[:80] + "..." if len(v_str) > 80 else v_str

    @staticmethod
    def _truncate(text: str | None, max_len: int) -> str:
        if not text:
            return "(empty)"
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."
