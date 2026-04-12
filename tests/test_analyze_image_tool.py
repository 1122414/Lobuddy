import base64
import tempfile
import types
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_nanobot_keys = [
    "nanobot",
    "nanobot.agent",
    "nanobot.agent.tools",
    "nanobot.agent.tools.base",
    "nanobot.agent.tools.schema",
]
_original_nanobot_modules = {k: sys.modules.get(k) for k in _nanobot_keys}

_nanobot = types.ModuleType("nanobot")
_nanobot.Nanobot = MagicMock()
sys.modules["nanobot"] = _nanobot

_agent = types.ModuleType("nanobot.agent")
sys.modules["nanobot.agent"] = _agent

_tools = types.ModuleType("nanobot.agent.tools")
sys.modules["nanobot.agent.tools"] = _tools

_base = types.ModuleType("nanobot.agent.tools.base")


class Tool:
    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def description(self) -> str:
        raise NotImplementedError

    @property
    def parameters(self):
        return {}

    @property
    def read_only(self) -> bool:
        return False

    @property
    def concurrency_safe(self) -> bool:
        return self.read_only and not getattr(self, "exclusive", False)

    @property
    def exclusive(self) -> bool:
        return False

    async def execute(self, **kwargs):
        raise NotImplementedError

    def cast_params(self, params):
        return params

    def validate_params(self, params):
        return []

    def to_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def tool_parameters(schema):
    def decorator(cls):
        cls._tool_parameters_schema = schema
        cls.parameters = property(lambda self: schema)
        return cls

    return decorator


_base.Tool = Tool
_base.tool_parameters = tool_parameters
sys.modules["nanobot.agent.tools.base"] = _base

_schema = types.ModuleType("nanobot.agent.tools.schema")


class StringSchema:
    def __init__(self, description: str = "", **kwargs):
        self._description = description

    def to_json_schema(self):
        return {"type": "string", "description": self._description}


def tool_parameters_schema(**kwargs):
    required = kwargs.pop("required", [])
    props = {}
    for k, v in kwargs.items():
        if hasattr(v, "to_json_schema"):
            props[k] = v.to_json_schema()
        else:
            props[k] = v
    return {"type": "object", "properties": props, "required": required}


_schema.StringSchema = StringSchema
_schema.tool_parameters_schema = tool_parameters_schema
sys.modules["nanobot.agent.tools.schema"] = _schema

from core.agent.tools.analyze_image_tool import AnalyzeImageTool
from app.config import Settings

for k, mod in _original_nanobot_modules.items():
    if mod is not None:
        sys.modules[k] = mod
    else:
        sys.modules.pop(k, None)


def _minimal_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def tool():
    settings = Settings(
        llm_api_key="test",
        llm_model="kimi-2.5",
        llm_multimodal_model="qwen-vl",
    )
    factory = MagicMock()
    factory.run_image_analysis = AsyncMock(return_value="image analysis result")
    return AnalyzeImageTool("/img.jpg", settings, factory)


class TestAnalyzeImageTool:
    def test_tool_name(self, tool):
        assert tool.name == "analyze_image"

    def test_tool_schema(self, tool):
        schema = tool.to_schema()
        assert schema["function"]["name"] == "analyze_image"
        assert "path" in schema["function"]["parameters"]["properties"]
        assert "prompt" in schema["function"]["parameters"]["properties"]
        assert schema["function"]["parameters"]["required"] == ["prompt"]

    def test_read_only(self, tool):
        assert tool.read_only is True

    def test_execute_delegates_to_factory(self, tool):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_minimal_png_bytes())
            path = f.name

        original_default = tool._default_image_path
        tool._default_image_path = path
        try:
            result = run_async(tool.execute(path=path, prompt="what?"))
            assert result == "image analysis result"
            tool._subagent_factory.run_image_analysis.assert_awaited_once()
            call_args = tool._subagent_factory.run_image_analysis.await_args.args
            assert call_args[0] == "what?"
            assert call_args[1] == path
        finally:
            tool._default_image_path = original_default
            Path(path).unlink(missing_ok=True)

    def test_execute_uses_default_path(self, tool):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_minimal_png_bytes())
            path = f.name

        original_default = tool._default_image_path
        tool._default_image_path = path
        try:
            result = run_async(tool.execute(path="", prompt="what?"))
            assert result == "image analysis result"
            tool._subagent_factory.run_image_analysis.assert_awaited_once()
        finally:
            tool._default_image_path = original_default
            Path(path).unlink(missing_ok=True)

    def test_execute_path_omitted_uses_default(self, tool):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_minimal_png_bytes())
            path = f.name

        original_default = tool._default_image_path
        tool._default_image_path = path
        try:
            result = run_async(tool.execute(prompt="what?"))
            assert result == "image analysis result"
            tool._subagent_factory.run_image_analysis.assert_awaited_once()
        finally:
            tool._default_image_path = original_default
            Path(path).unlink(missing_ok=True)

    def test_execute_rejects_mismatched_path(self, tool):
        result = run_async(tool.execute(path="/another.jpg", prompt="what?"))
        assert "Invalid image path" in result
        tool._subagent_factory.run_image_analysis.assert_not_called()

    def test_execute_no_path_error(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        factory = MagicMock()
        tool = AnalyzeImageTool(None, settings, factory)
        result = run_async(tool.execute(path="", prompt="what?"))
        assert "No image path provided" in result

    def test_execute_returns_validation_error(self, tool):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"not an image")
            path = f.name
        try:
            result = run_async(tool.execute(path=path, prompt="what?"))
            assert "Error:" in result
            tool._subagent_factory.run_image_analysis.assert_not_called()
        finally:
            Path(path).unlink(missing_ok=True)
