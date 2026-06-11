from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolExecutionRequest:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    output: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolTrace:
    tool_name: str
    arguments: dict[str, Any]
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def execute(self, **kwargs: Any) -> ToolResult:
        ...


class ToolHook(Protocol):
    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        ...

    def after_execute(
        self,
        request: ToolExecutionRequest,
        result: ToolResult,
    ) -> ToolResult:
        ...
