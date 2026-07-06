from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import (
    HookContext,
    HookTraceItem,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHook,
    ToolResult,
    ToolTrace,
)

ToolInvoker = Callable[[str, dict[str, Any]], Awaitable[Any]]


class ToolExecutionDenied(RuntimeError):
    """旧异常符号保留（旧测试/插件可能 import）；新 executor 不再依赖它。"""


@dataclass
class ToolExecutor:
    """工具执行器：三段式（pre hooks → invoker → post hooks）+ preflight。

    与 Registry 解耦：构造为 ToolExecutor(hooks, invoker)，不持有 Registry 引用。
    旧调用点传 registry= 兼容：构造期包成 invoker，不存 registry 字段。
    """

    hooks: list[ToolHook] = field(default_factory=list)
    invoker: ToolInvoker | None = None
    # 兼容旧 ToolExecutor(registry=...) 构造；不作为字段长期持有
    registry: Any = None

    def __post_init__(self) -> None:
        if self.invoker is None and self.registry is not None:
            registry = self.registry

            async def _compat_invoker(name: str, arguments: dict[str, Any]) -> Any:
                return await registry.execute(name, arguments)

            self.invoker = _compat_invoker

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        current_arguments = dict(request.arguments)
        pre_trace: list[HookTraceItem] = []
        post_trace: list[HookTraceItem] = []

        # 4a pre hooks
        denied, current_arguments = await self._run_pre_hooks(
            request=request,
            current_arguments=current_arguments,
            traces=pre_trace,
        )
        if denied is not None:
            reason = denied
            return ToolExecutionResult(
                status="denied",
                output=reason,
                final_arguments=current_arguments,
                pre_hook_trace=pre_trace,
                post_hook_trace=post_trace,
            )

        # 4b invoker
        if self.invoker is None:
            return ToolExecutionResult(
                status="error",
                output="ToolExecutor 未配置 invoker",
                final_arguments=current_arguments,
                pre_hook_trace=pre_trace,
                post_hook_trace=post_trace,
            )
        try:
            output = await self.invoker(request.tool_name, current_arguments)
        except Exception as exc:
            # 4c-err post_tool_error（不 fail_open）
            await self._run_post_hooks(
                event="post_tool_error",
                request=request,
                current_arguments=current_arguments,
                traces=post_trace,
                error=str(exc),
                fail_open=False,
            )
            return ToolExecutionResult(
                status="error",
                output=f"工具执行出错: {exc}",
                final_arguments=current_arguments,
                pre_hook_trace=pre_trace,
                post_hook_trace=post_trace,
            )

        # 4c-ok post_tool_use（fail_open=True：post hook 自身挂了不污染主链路）
        await self._run_post_hooks(
            event="post_tool_use",
            request=request,
            current_arguments=current_arguments,
            traces=post_trace,
            result=output,
            fail_open=True,
        )
        return ToolExecutionResult(
            status="success",
            output=output,
            final_arguments=current_arguments,
            pre_hook_trace=pre_trace,
            post_hook_trace=post_trace,
        )

    async def preflight(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """只跑 pre hooks、不调 invoker。语义收紧：不执行真实工具。"""
        current_arguments = dict(request.arguments)
        pre_trace: list[HookTraceItem] = []
        denied, current_arguments = await self._run_pre_hooks(
            request=request,
            current_arguments=current_arguments,
            traces=pre_trace,
        )
        if denied is not None:
            return ToolExecutionResult(
                status="denied",
                output=denied,
                final_arguments=current_arguments,
                pre_hook_trace=pre_trace,
            )
        return ToolExecutionResult(
            status="pass",
            output="",
            final_arguments=current_arguments,
            pre_hook_trace=pre_trace,
        )

    async def _run_pre_hooks(
        self,
        *,
        request: ToolExecutionRequest,
        current_arguments: dict[str, Any],
        traces: list[HookTraceItem],
    ) -> tuple[str | None, dict[str, Any]]:
        """返回 (deny_reason | None, 改后的参数)。deny_reason 非 None 表示被短路。"""
        for hook in self.hooks:
            if hook.event != "pre_tool_use":
                continue
            ctx = HookContext(
                event="pre_tool_use",
                request=request,
                current_arguments=dict(current_arguments),
            )
            if not hook.matches(ctx):
                traces.append(
                    HookTraceItem(hook_name=hook.name, event=hook.event, matched=False)
                )
                continue
            outcome = hook.run(ctx)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if outcome.updated_input is not None:
                current_arguments = dict(outcome.updated_input)
            traces.append(
                HookTraceItem(
                    hook_name=hook.name,
                    event=hook.event,
                    matched=True,
                    decision=outcome.decision,
                    reason=outcome.reason,
                )
            )
            if outcome.decision == "deny":
                return outcome.reason.strip() or "工具调用被拦截", current_arguments
        return None, current_arguments

    async def _run_post_hooks(
        self,
        *,
        event: str,
        request: ToolExecutionRequest,
        current_arguments: dict[str, Any],
        traces: list[HookTraceItem],
        result: Any = "",
        error: str = "",
        fail_open: bool,
    ) -> None:
        for hook in self.hooks:
            if hook.event != event:
                continue
            ctx = HookContext(
                event=event,  # type: ignore[arg-type]
                request=request,
                current_arguments=dict(current_arguments),
                result=result,
                error=error,
            )
            if not hook.matches(ctx):
                traces.append(
                    HookTraceItem(hook_name=hook.name, event=hook.event, matched=False)
                )
                continue
            try:
                outcome = hook.run(ctx)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                traces.append(
                    HookTraceItem(
                        hook_name=hook.name,
                        event=hook.event,
                        matched=True,
                        decision=outcome.decision,
                        reason=outcome.reason,
                    )
                )
            except Exception as exc:
                if fail_open:
                    traces.append(
                        HookTraceItem(
                            hook_name=hook.name,
                            event=hook.event,
                            matched=True,
                            reason=f"post hook error: {exc}",
                        )
                    )
                    continue
                raise

    # ── 旧调用点兼容薄壳 ──────────────────────────────────────────
    # 保留 execute / execute_async 旧签名，内部包成 ToolExecutionRequest 转发到新接口。
    # 旧调用方（reasoner.execute_async(...)）迁移期可继续用；新调用方应直接用 execute(request)。

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str = "",
        tool_batch: dict[str, Any] | None = None,
        tool_batch_index: int = 0,
    ) -> tuple[ToolResult, ToolTrace]:
        """旧签名薄壳：返回 (ToolResult, ToolTrace) 兼容现有 reasoner 调用点。"""
        request = ToolExecutionRequest(
            tool_name=tool_name,
            arguments=dict(arguments),
            call_id=call_id,
            tool_batch=dict(tool_batch) if tool_batch else {},
            tool_batch_index=tool_batch_index,
        )
        result = await self.execute(request)
        # invoker（registry.execute）返回的就是 ToolResult；若已是 ToolResult 直接用，
        # 否则包一层。避免嵌套 ToolResult(ToolResult(...))。
        if isinstance(result.output, ToolResult):
            tool_result = ToolResult(
                tool_name=result.output.tool_name or tool_name,
                output=result.output.output,
                is_error=result.output.is_error or result.status != "success",
                metadata={
                    **result.output.metadata,
                    "pre_hook_trace": [
                        dict(t.__dict__) for t in result.pre_hook_trace
                    ],
                    "post_hook_trace": [
                        dict(t.__dict__) for t in result.post_hook_trace
                    ],
                },
            )
        else:
            tool_result = ToolResult(
                tool_name=tool_name,
                output=result.output,
                is_error=result.status != "success",
                metadata={
                    "pre_hook_trace": [
                        dict(t.__dict__) for t in result.pre_hook_trace
                    ],
                    "post_hook_trace": [
                        dict(t.__dict__) for t in result.post_hook_trace
                    ],
                },
            )
        trace = ToolTrace(
            tool_name=tool_name,
            arguments=result.final_arguments,
            status=result.status,
        )
        return tool_result, trace