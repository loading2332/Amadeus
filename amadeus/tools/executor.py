from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amadeus.tools.base import ToolExecutionRequest, ToolHook, ToolResult, ToolTrace
from amadeus.tools.registry import ToolRegistry


class ToolExecutionDenied(RuntimeError):
    pass


@dataclass
class ToolExecutor:
    registry: ToolRegistry
    hooks: list[ToolHook] | None = None

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str = "",
        tool_batch: dict[str, Any] | None = None,
        tool_batch_index: int = 0,
    ) -> tuple[ToolResult, ToolTrace]:
        request = ToolExecutionRequest(
            tool_name=tool_name,
            arguments=dict(arguments),
            call_id=call_id,
            tool_batch=dict(tool_batch) if tool_batch else {},
            tool_batch_index=tool_batch_index,
        )
        try:
            for hook in self.hooks or []:
                request = hook.before_execute(request)
            tool = self.registry.get(tool_name)
            if tool is None:
                raise KeyError(f"unknown tool: {tool_name}")
            result = tool.execute(**request.arguments)
            for hook in self.hooks or []:
                result = hook.after_execute(request, result)
            return (
                result,
                ToolTrace(
                    tool_name=tool_name,
                    arguments=request.arguments,
                    status="success",
                ),
            )
        except ToolExecutionDenied as error:
            return (
                ToolResult(tool_name=tool_name, output={"error": str(error)}, is_error=True),
                ToolTrace(
                    tool_name=tool_name,
                    arguments=request.arguments,
                    status="denied",
                ),
            )
        except Exception as error:
            return (
                ToolResult(tool_name=tool_name, output={"error": str(error)}, is_error=True),
                ToolTrace(
                    tool_name=tool_name,
                    arguments=request.arguments,
                    status="error",
                ),
            )
