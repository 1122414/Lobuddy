"""Tests for analyze_image nanobot tool."""

import types
import pytest
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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

from app.config import Settings
from core.agent.tools.analyze_image_tool import AnalyzeImageTool


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAnalyzeImageTool:
    @pytest.fixture
    def tool(self):
        settings = Settings(
            llm_api_key="test",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen-vl",
        )
        return AnalyzeImageTool("/img.jpg", settings)

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

    def test_execute_delegates_to_analyzer(self, tool):
        with patch(
            "core.agent.tools.analyze_image_tool.ImageAnalyzer.analyze",
            new_callable=AsyncMock,
            return_value="image analysis result",
        ) as mock_analyze:
            result = run_async(tool.execute(path="/img.jpg", prompt="what?"))
        assert result == "image analysis result"
        mock_analyze.assert_awaited_once_with("/img.jpg", "what?")

    def test_execute_uses_default_path(self, tool):
        with patch(
            "core.agent.tools.analyze_image_tool.ImageAnalyzer.analyze",
            new_callable=AsyncMock,
            return_value="result",
        ) as mock_analyze:
            result = run_async(tool.execute(path="", prompt="what?"))
        assert result == "result"
        mock_analyze.assert_awaited_once_with("/img.jpg", "what?")

    def test_execute_path_omitted_uses_default(self, tool):
        with patch(
            "core.agent.tools.analyze_image_tool.ImageAnalyzer.analyze",
            new_callable=AsyncMock,
            return_value="result",
        ) as mock_analyze:
            result = run_async(tool.execute(prompt="what?"))
        assert result == "result"
        mock_analyze.assert_awaited_once_with("/img.jpg", "what?")

    def test_execute_rejects_mismatched_path(self, tool):
        with patch(
            "core.agent.tools.analyze_image_tool.ImageAnalyzer.analyze",
            new_callable=AsyncMock,
            return_value="result",
        ) as mock_analyze:
            result = run_async(tool.execute(path="/another.jpg", prompt="what?"))
        assert "Invalid image path" in result
        mock_analyze.assert_not_called()

    def test_execute_no_path_error(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        tool = AnalyzeImageTool(None, settings)
        result = run_async(tool.execute(path="", prompt="what?"))
        assert "No image path provided" in result
