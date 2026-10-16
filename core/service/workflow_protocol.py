"""Immutable declarative workflow contract; no executable expressions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    kind: Literal["context", "model", "tool", "condition", "verify", "output"]
    after: list[str] = Field(default_factory=list, max_length=12)
    tool: Literal["lobuddy_organize", "lobuddy_digest", "lobuddy_read_file"] | None = None
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    source: str = "input"
    format: Literal["pretty", "compact"] = "pretty"
    prompt: str = Field(default="", max_length=2000)
    operator: Literal["exists", "equals"] = "exists"
    expected: JsonValue = None
    when: str = ""


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=12)
    permissions: list[Literal["lobuddy_organize", "lobuddy_digest", "lobuddy_read_file"]] = Field(
        default_factory=list
    )
    repairs: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowDefinition:
        seen: set[str] = {"input"}
        for node in self.nodes:
            if node.id in seen or any(dep not in seen for dep in node.after):
                raise ValueError("节点重复、环或未按拓扑顺序声明")
            refs = [node.source, node.when] + [
                v[1:] for v in node.arguments.values() if isinstance(v, str) and v.startswith("$")
            ]
            for ref in refs:
                if ref and ref.split(".")[0] not in seen:
                    raise ValueError("引用必须来自输入或已完成节点")
                if ref and not all(part.replace("_", "").isalnum() for part in ref.split(".")):
                    raise ValueError("仅允许结构化字段引用")
            if node.kind == "tool" and (node.tool is None or node.tool not in self.permissions):
                raise ValueError("工具超出工作流权限范围")
            if node.kind != "tool" and node.tool is not None:
                raise ValueError("非工具节点不得声明工具")
            seen.add(node.id)
        if self.nodes[-1].kind != "output":
            raise ValueError("最后一个节点必须输出结果")
        return self


class WorkflowReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version_id: str = Field(min_length=1, max_length=128)


class WorkflowProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    definition: WorkflowDefinition
    reason: str = Field(min_length=1, max_length=1000)


class WorkflowView(BaseModel):
    version_id: str
    parent_id: str
    definition: WorkflowDefinition
    status: str
    reason: str
    evidence: list[str]
    diff: str
    evaluation: dict[str, JsonValue]
    observed: int
    active: bool


class ContextProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["pretty", "compact"]
    reason: str = Field(min_length=1, max_length=500)
