from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import (
    HookContext,
    HookOutcome,
    ToolExecutionRequest,
    ToolResult,
)
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output={"echo": kwargs.get("text", "")})


def _make_invoker(registry: ToolRegistry, call_log: list | None = None):
    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        if call_log is not None:
            call_log.append((name, dict(arguments)))
        return await registry.execute(name, arguments)

    return invoker


class RewriteTextHook:
    """改参不 deny：把 text 改成大写后放行。"""

    name = "rewrite_text"
    event = "pre_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        return ctx.request.tool_name == "echo"

    def run(self, ctx: HookContext) -> HookOutcome:
        return HookOutcome(
            decision="pass",
            updated_input={**ctx.request.arguments, "text": str(ctx.request.arguments.get("text", "")).upper()},
        )


class DenyAlwaysHook:
    name = "deny_always"
    event = "pre_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        return True

    def run(self, ctx: HookContext) -> HookOutcome:
        return HookOutcome(decision="deny", reason="denied by test hook")


class RewriteAndDenyHook:
    """改参 + deny 同时：updated_input 改了，但 decision=deny。"""

    name = "rewrite_and_deny"
    event = "pre_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        return True

    def run(self, ctx: HookContext) -> HookOutcome:
        return HookOutcome(
            decision="deny",
            updated_input={**ctx.request.arguments, "text": "rewritten"},
            reason="deny with rewrite",
        )


class FailingPostHook:
    """post hook 自身抛错，fail_open 应保护主链路。"""

    name = "failing_post"
    event = "post_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        return True

    def run(self, ctx: HookContext) -> HookOutcome:
        raise RuntimeError("post hook crashed")


class FailingPostErrorHook(FailingPostHook):
    name = "failing_post_error"
    event = "post_tool_error"


class FailingPreMatchHook:
    name = "failing_pre_match"
    event = "pre_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        del ctx
        raise RuntimeError("pre match crashed")

    def run(self, ctx: HookContext) -> HookOutcome:
        del ctx
        return HookOutcome()


class FailingPreRunHook:
    name = "failing_pre_run"
    event = "pre_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        del ctx
        return True

    def run(self, ctx: HookContext) -> HookOutcome:
        del ctx
        raise RuntimeError("pre run crashed")


class FailingPostMatchHook:
    name = "failing_post_match"
    event = "post_tool_use"

    def matches(self, ctx: HookContext) -> bool:
        del ctx
        raise RuntimeError("post match crashed")

    def run(self, ctx: HookContext) -> HookOutcome:
        del ctx
        return HookOutcome()


def test_pre_hook_can_rewrite_without_deny():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(hooks=[RewriteTextHook()], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    assert result.status == "success"
    assert result.final_arguments == {"text": "HELLO"}    # 改参生效
    assert result.output.output == {"echo": "HELLO"}
    assert not any(t.decision == "deny" for t in result.pre_hook_trace)


def test_pre_hook_can_deny_without_rewrite():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(hooks=[DenyAlwaysHook()], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    assert result.status == "denied"
    assert "denied by test hook" in result.output
    # 参数未被改
    assert result.final_arguments == {"text": "hello"}


def test_pre_hook_can_rewrite_and_deny_simultaneously():
    registry = ToolRegistry()
    registry.register(EchoTool())
    call_log: list = []
    executor = ToolExecutor(
        hooks=[RewriteAndDenyHook()], invoker=_make_invoker(registry, call_log)
    )

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    assert result.status == "denied"
    assert result.final_arguments == {"text": "rewritten"}    # 改参生效
    # invoker 未被调用（deny 短路）
    assert call_log == []


def test_post_hook_fail_open_does_not_pollute_main_path():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(
        hooks=[FailingPostHook()], invoker=_make_invoker(registry)
    )

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    # post hook 抛错不应让成功变成 error
    assert result.status == "success"
    assert result.output.output == {"echo": "hello"}
    # post trace 记录了 hook 抛错
    assert any("post hook error" in (t.reason or "") for t in result.post_hook_trace)


def test_post_error_hook_fail_open_preserves_tool_error():
    async def broken_invoker(name: str, arguments: dict[str, Any]) -> Any:
        del name, arguments
        raise RuntimeError("tool crashed")

    executor = ToolExecutor(hooks=[FailingPostErrorHook()], invoker=broken_invoker)

    result = asyncio.run(
        executor.execute(ToolExecutionRequest(tool_name="echo", arguments={}))
    )

    assert result.status == "error"
    assert "tool crashed" in str(result.output)
    assert any("post hook error" in (t.reason or "") for t in result.post_hook_trace)


def test_preflight_does_not_invoke_invoker():
    registry = ToolRegistry()
    registry.register(EchoTool())
    call_log: list = []
    executor = ToolExecutor(
        hooks=[RewriteTextHook()], invoker=_make_invoker(registry, call_log)
    )

    result = asyncio.run(
        executor.preflight(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    # preflight 跑 pre hooks（改参生效），但不调 invoker
    assert result.status == "pass"
    assert result.final_arguments == {"text": "HELLO"}
    assert call_log == []    # invoker 没被调用


def test_preflight_returns_deny_when_hook_denies():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(hooks=[DenyAlwaysHook()], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.preflight(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    assert result.status == "denied"
    assert "denied by test hook" in result.output


def test_pre_hook_match_failure_returns_structured_error():
    call_log: list = []

    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        call_log.append((name, arguments))
        return "unexpected"

    executor = ToolExecutor(hooks=[FailingPreMatchHook()], invoker=invoker)

    result = asyncio.run(
        executor.execute(ToolExecutionRequest(tool_name="echo", arguments={}))
    )

    assert result.status == "error"
    assert "failing_pre_match" in str(result.output)
    assert "pre match crashed" in str(result.output)
    assert call_log == []


def test_preflight_pre_hook_run_failure_returns_structured_error():
    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        del name, arguments
        return "unexpected"

    executor = ToolExecutor(hooks=[FailingPreRunHook()], invoker=invoker)

    result = asyncio.run(
        executor.preflight(ToolExecutionRequest(tool_name="echo", arguments={}))
    )

    assert result.status == "error"
    assert "failing_pre_run" in str(result.output)
    assert "pre run crashed" in str(result.output)


def test_post_hook_match_failure_is_fail_open_and_traced():
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(
        hooks=[FailingPostMatchHook()], invoker=_make_invoker(registry)
    )

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(tool_name="echo", arguments={"text": "hello"})
        )
    )

    assert result.status == "success"
    assert result.output.output == {"echo": "hello"}
    assert result.post_hook_trace[-1].matched is False
    assert "matches" in result.post_hook_trace[-1].reason
    assert "post match crashed" in result.post_hook_trace[-1].reason


def test_missing_tool_is_recorded_as_error():
    registry = ToolRegistry()
    executor = ToolExecutor(hooks=[], invoker=_make_invoker(registry))

    result = asyncio.run(
        executor.execute(ToolExecutionRequest(tool_name="missing", arguments={}))
    )

    assert result.status == "error"
    assert "missing" in str(result.output)
    assert "不存在" in str(result.output)
