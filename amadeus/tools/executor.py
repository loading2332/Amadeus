from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from amadeus.tools.base import (
    HookContext,
    HookEvent,
    HookTraceItem,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHook,
)

ToolInvoker = Callable[[str, dict[str, Any]], Awaitable[Any]]


class HookExecutionError(RuntimeError):
    """把 hook 边界内的任意异常归一为可观察的执行错误。"""

    def __init__(
        self,
        hook_name: str,
        event: HookEvent,
        stage: str,
        cause: Exception,
    ) -> None:
        self.hook_name = hook_name
        self.event = event
        self.stage = stage
        self.cause = cause
        super().__init__(f"hook {hook_name} ({event}.{stage}) failed: {cause}")


@dataclass
class ToolExecutor:
    """工具执行器：三段式（pre hooks → invoker → post hooks）+ preflight。

    与 Registry 解耦：构造为 ToolExecutor(hooks, invoker)，只依赖 invoker port。
    """

    hooks: list[ToolHook]
    invoker: ToolInvoker

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        current_arguments = dict(request.arguments)
        pre_trace: list[HookTraceItem] = []
        post_trace: list[HookTraceItem] = []

        # 4a pre hooks。pre hook 是执行边界的一部分，异常不能击穿 Reasoner。
        try:
            denied, current_arguments = await self._run_pre_hooks(
                request=request,
                current_arguments=current_arguments,
                traces=pre_trace,
            )
        except HookExecutionError as exc:
            return ToolExecutionResult(
                status="error",
                output=f"工具执行出错: {exc}",
                final_arguments=dict(current_arguments),
                pre_hook_trace=pre_trace,
                post_hook_trace=post_trace,
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
        try:
            output = await self.invoker(request.tool_name, current_arguments)
        except Exception as exc:
            # 4c-err post_tool_error 也 fail-open，避免 hook 错误覆盖原始工具错误
            await self._run_post_hooks(
                event="post_tool_error",
                request=request,
                current_arguments=current_arguments,
                traces=post_trace,
                error=str(exc),
                fail_open=True,
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
        try:
            denied, current_arguments = await self._run_pre_hooks(
                request=request,
                current_arguments=current_arguments,
                traces=pre_trace,
            )
        except HookExecutionError as exc:
            return ToolExecutionResult(
                status="error",
                output=f"工具执行出错: {exc}",
                final_arguments=dict(current_arguments),
                pre_hook_trace=pre_trace,
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
            try:
                matched = hook.matches(ctx)
            except Exception as exc:
                traces.append(
                    HookTraceItem(
                        hook_name=hook.name,
                        event=hook.event,
                        matched=False,
                        reason=f"pre hook error (matches): {exc}",
                    )
                )
                raise HookExecutionError(
                    hook.name, hook.event, "matches", exc
                ) from exc
            if not matched:
                traces.append(
                    HookTraceItem(hook_name=hook.name, event=hook.event, matched=False)
                )
                continue
            try:
                outcome = hook.run(ctx)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                if outcome.updated_input is not None:
                    # 原地更新，确保后续 hook 失败时 execute/preflight 仍能看到
                    # 已经生效的最终参数，而不是回退到最初请求。
                    current_arguments.clear()
                    current_arguments.update(outcome.updated_input)
                trace = HookTraceItem(
                    hook_name=hook.name,
                    event=hook.event,
                    matched=True,
                    decision=outcome.decision,
                    reason=outcome.reason,
                )
            except Exception as exc:
                traces.append(
                    HookTraceItem(
                        hook_name=hook.name,
                        event=hook.event,
                        matched=True,
                        reason=f"pre hook error (run): {exc}",
                    )
                )
                raise HookExecutionError(hook.name, hook.event, "run", exc) from exc
            traces.append(trace)
            if outcome.decision == "deny":
                return outcome.reason.strip() or "工具调用被拦截", current_arguments
        return None, current_arguments

    async def _run_post_hooks(
        self,
        *,
        event: HookEvent,
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
                event=event,
                request=request,
                current_arguments=dict(current_arguments),
                result=result,
                error=error,
            )
            try:
                matched = hook.matches(ctx)
            except Exception as exc:
                if fail_open:
                    traces.append(
                        HookTraceItem(
                            hook_name=hook.name,
                            event=hook.event,
                            matched=False,
                            reason=f"post hook error (matches): {exc}",
                        )
                    )
                    continue
                raise HookExecutionError(
                    hook.name, hook.event, "matches", exc
                ) from exc
            if not matched:
                traces.append(
                    HookTraceItem(hook_name=hook.name, event=hook.event, matched=False)
                )
                continue
            try:
                outcome = hook.run(ctx)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                trace = HookTraceItem(
                    hook_name=hook.name,
                    event=hook.event,
                    matched=True,
                    decision=outcome.decision,
                    reason=outcome.reason,
                )
            except Exception as exc:
                if fail_open:
                    traces.append(
                        HookTraceItem(
                            hook_name=hook.name,
                            event=hook.event,
                            matched=True,
                            reason=f"post hook error (run): {exc}",
                        )
                    )
                    continue
                raise HookExecutionError(hook.name, hook.event, "run", exc) from exc
            traces.append(trace)
