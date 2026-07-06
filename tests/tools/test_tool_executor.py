from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import HookContext, HookOutcome, ToolExecutionRequest, ToolResult
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo the provided text."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


class DenySecretHook:
    name = "deny_secret"
    event = "pre_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        return ctx.request.tool_name == "echo"

    def run(self, ctx: HookContext) -> HookOutcome:
        if ctx.request.arguments.get("text") == "secret":
            return HookOutcome(decision="deny", reason="secret not allowed")
        return HookOutcome(decision="pass")


def _make_invoker(registry: ToolRegistry):
    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        return await registry.execute(name, arguments)

    return invoker


def test_executor_runs_tool_and_returns_success():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(hooks=[], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    assert result.status == "success"
    assert result.output.tool_name == "echo"
    assert result.output.output == {"echo": "hello"}
    assert result.final_arguments == {"text": "hello"}


def test_executor_denies_via_pre_hook():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(hooks=[DenySecretHook()], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "secret"})
        )
    )

    assert result.status == "denied"
    assert "secret not allowed" in result.output
    assert any(t.decision == "deny" for t in result.pre_hook_trace)


def test_executor_wraps_tool_exceptions():
    @dataclass
    class BrokenTool:
        name: str = "broken"
        description: str = "Always fails."
        parameters: dict[str, Any] = field(
            default_factory=lambda: {"type": "object", "properties": {}}
        )

        def execute(self, **kwargs: Any) -> ToolResult:
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(BrokenTool())
    executor = ToolExecutor(hooks=[], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.execute(ToolExecutionRequest(tool_name="broken", arguments={}))
    )

    assert result.status == "error"
    assert "boom" in result.output