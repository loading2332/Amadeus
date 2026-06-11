from __future__ import annotations

from dataclasses import dataclass, field

from amadeus.tools.base import ToolExecutionRequest, ToolResult
from amadeus.tools.executor import ToolExecutionDenied, ToolExecutor
from amadeus.tools.registry import ToolRegistry


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo the provided text."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
    )

    def execute(self, **kwargs):
        return ToolResult(tool_name=self.name, output={"echo": kwargs["text"]})


class DenySecretHook:
    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        if request.arguments.get("text") == "secret":
            raise ToolExecutionDenied("secret not allowed")
        return request

    def after_execute(self, request: ToolExecutionRequest, result: ToolResult) -> ToolResult:
        return result


def test_executor_runs_tool_and_returns_trace():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(registry=registry)

    result, trace = executor.execute("echo", {"text": "hello"})

    assert result.output == {"echo": "hello"}
    assert trace.status == "success"


def test_executor_denies_via_pre_hook():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(registry=registry, hooks=[DenySecretHook()])

    result, trace = executor.execute("echo", {"text": "secret"})

    assert result.is_error is True
    assert "secret not allowed" in result.output["error"]
    assert trace.status == "denied"


def test_executor_wraps_tool_exceptions():
    @dataclass
    class BrokenTool:
        name: str = "broken"
        description: str = "Always fails."
        parameters: dict = field(
            default_factory=lambda: {"type": "object", "properties": {}}
        )

        def execute(self, **kwargs):
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(BrokenTool())
    executor = ToolExecutor(registry=registry)

    result, trace = executor.execute("broken", {})

    assert result.is_error is True
    assert result.output["error"] == "boom"
    assert trace.status == "error"
