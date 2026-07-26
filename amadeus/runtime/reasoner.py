from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from amadeus.events import EventBus, ToolCallCompleted, ToolCallStarted
from amadeus.provider import LLMProvider, LLMResponse
from amadeus.runtime.lifecycle import AfterStepContext, BeforeStepContext
from amadeus.runtime.phase import Phase
from amadeus.runtime.step_phases import (
    AfterStepFrame,
    AfterStepInput,
    BeforeStepFrame,
    BeforeStepInput,
)
from amadeus.runtime.streaming import TurnStreamSink
from amadeus.runtime.tool_runtime import (
    append_assistant_tool_calls,
    append_tool_result,
    tool_call_batch_snapshot,
)
from amadeus.session.identity import SessionRef
from amadeus.tools.base import ToolExecutionRequest, ToolExecutionResult, ToolResult
from amadeus.tools.discovery import SessionToolDiscoveryStore, TurnVisibleSet
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry
from amadeus.types import ReasonerResult

_REPEAT_GUARD_WINDOW = 4
_TOOL_SEARCH_NAME = "tool_search"
_UNLOCK_GUIDE_TEMPLATE = (
    "工具 '{name}' 当前未加载（schema 不可见）。请先调用 "
    "tool_search(query=\"select:{name}\") 加载，然后再调用该工具。"
)
_INVALID_ARGUMENTS_TEMPLATE = (
    "工具 '{name}' 的 arguments 不是合法 JSON，本次调用未执行。"
    "解析错误：{error}。请修正参数为合法 JSON 对象后重新调用。"
)


async def _check_cancelled(stream_sink: TurnStreamSink | None) -> None:
    if stream_sink is not None:
        await stream_sink.check_cancelled()


async def _publish_tool(
    stream_sink: TurnStreamSink | None,
    activity_id: str,
    tool_name: str,
    state: str,
) -> None:
    if stream_sink is not None:
        await stream_sink.publish_tool_activity(
            activity_id=activity_id,
            tool_name=tool_name,
            state=state,
        )


@dataclass
class Reasoner:
    """Independent reasoning boundary — owns provider call and step-level lifecycle.

    *PassiveRuntime* owns turn-level lifecycle (before_turn, before_reasoning,
    prompt_render, after_reasoning, after_turn) and delegates provider + tool
    loop to *Reasoner*.

    For ordinary chat (no *tool_calls* returned), ``reason()`` calls the
    provider and returns the assistant reply directly.  When tool_calls are
    present, Reasoner runs the multi-step tool loop, optionally guarded by
    before_step / after_step lifecycle phases.
    """

    provider: LLMProvider
    tool_executor: ToolExecutor | None = None
    max_tool_iterations: int = 10
    event_bus: EventBus = field(default_factory=EventBus)

    # 注入 registry 时启用按需解锁；不注入即运行无工具对话。
    tool_registry: ToolRegistry | None = None
    _discovery_store: SessionToolDiscoveryStore = field(
        default_factory=SessionToolDiscoveryStore,
        init=False,
        repr=False,
    )

    # Step lifecycle phases — injected by PassiveRuntime / PassiveApp.
    # Executed by Reasoner during the tool loop.
    before_step: Phase[BeforeStepInput, BeforeStepContext, BeforeStepFrame] | None = None
    after_step: Phase[AfterStepInput, AfterStepContext, AfterStepFrame] | None = None

    @classmethod
    def from_response(cls, response: LLMResponse) -> ReasonerResult:
        """Package an already-completed LLM response into a ``ReasonerResult``.

        Used when ``PassiveRuntime`` already holds the provider response and
        only needs result packaging.  For the full flow (provider call +
        packaging), use :meth:`reason` instead.
        """
        if response.content is None:
            raise ValueError("LLM response did not include assistant content")
        return ReasonerResult(
            reply=response.content,
            tool_chain=[],
            invocations=[],
            provider_raw=response.raw,
            metadata={
                "model": response.model,
                "response_id": response.response_id,
                "usage": response.usage,
            },
        )

    async def reason(
        self,
        messages: Sequence[dict[str, Any]],
        session: SessionRef | None = None,
        stream_sink: TurnStreamSink | None = None,
    ) -> ReasonerResult:
        """Run a reasoning turn: provider call → optional tool loop → result."""
        visible_set = self._create_visible_set(session)
        tool_schemas = self._schemas_for_visible_set(visible_set)
        await _check_cancelled(stream_sink)
        response = await self._chat_with_stream(
            list(messages),
            tools=list(tool_schemas) if tool_schemas is not None else None,
            stream_sink=stream_sink,
        )

        if not response.tool_calls:
            if response.content is None:
                raise ValueError("LLM response did not include assistant content")
            return ReasonerResult(
                reply=response.content,
                tool_chain=[],
                invocations=[],
                provider_raw=response.raw,
                metadata={
                    "model": response.model,
                    "response_id": response.response_id,
                    "usage": response.usage,
                },
            )

        return await self._run_tool_loop(
            messages=list(messages),
            response=response,
            session=session,
            visible_set=visible_set,
            stream_sink=stream_sink,
        )

    async def _run_tool_loop(
        self,
        *,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        session: SessionRef | None = None,
        visible_set: TurnVisibleSet | None = None,
        stream_sink: TurnStreamSink | None = None,
    ) -> ReasonerResult:
        if self.tool_executor is None:
            raise ValueError("LLM requested tools but no tool executor is configured")

        loop_messages = list(messages)
        tool_chain: list[dict[str, Any]] = []
        invocations: list[Any] = []
        current_response = response
        iterations = 0
        tools_used: list[str] = []
        step_telemetry: list[dict[str, Any]] = []
        repeat_history: list[tuple[str, str]] = []

        def _current_schemas() -> list[dict[str, Any]] | None:
            return self._schemas_for_visible_set(visible_set)

        while current_response.tool_calls:
            await _check_cancelled(stream_sink)
            if iterations >= self.max_tool_iterations:
                break

            # ── before_step lifecycle gate ──────────────────────────────
            if self.before_step is not None:
                if session is None:  # pragma: no cover - defensive invariant
                    raise RuntimeError("reasoner before_step requires a structured session")
                before_step = await self.before_step.run(
                    BeforeStepInput(
                        session=session,
                        iteration=iterations,
                        messages=loop_messages,
                        tool_schemas=_current_schemas(),
                    )
                )
                if before_step.extra_hints:
                    loop_messages.append(
                        {
                            "role": "system",
                            "content": "\n".join(before_step.extra_hints),
                        }
                    )
                if before_step.early_stop_reply is not None:
                    return ReasonerResult(
                        reply=before_step.early_stop_reply,
                        tool_chain=tool_chain,
                        invocations=invocations,
                        provider_raw=response.raw,
                        metadata={
                            "tools_used": tools_used,
                            "step_telemetry": step_telemetry,
                            "stop_reason": "before_step_early_stop",
                            "react_stats": {
                                "iteration_count": iterations,
                                "tools_used_count": len(tools_used),
                            },
                        },
                    )

            # ── Batch snapshot ──────────────────────────────────────────
            tool_batch = tool_call_batch_snapshot(current_response.tool_calls)

            # ── Append assistant tool call message ──────────────────────
            append_assistant_tool_calls(
                loop_messages,
                content=current_response.content,
                tool_calls=current_response.tool_calls,
            )

            # ── Execute tool calls ──────────────────────────────────────
            current_step: dict[str, Any] = {
                "text": current_response.content or "",
                "calls": [],
            }
            for batch_index, tool_call in enumerate(current_response.tool_calls):
                activity_id = tool_call.id or (
                    f"tool-{iterations}-{batch_index}-{tool_call.name}"
                )
                await _check_cancelled(stream_sink)
                await _publish_tool(
                    stream_sink,
                    activity_id,
                    tool_call.name,
                    "started",
                )
                # ── 参数 JSON 解析失败：不执行工具，把错误作为 tool result
                # 回传给模型自纠（provider 已把畸形 arguments 降级为 {} + 标记）──
                if tool_call.arguments_error is not None:
                    error_text = _INVALID_ARGUMENTS_TEMPLATE.format(
                        name=tool_call.name,
                        error=tool_call.arguments_error,
                    )
                    if session is not None:
                        await self.event_bus.emit(
                            ToolCallStarted(
                                session=session,
                                iteration=iterations,
                                call_id=tool_call.id,
                                tool_name=tool_call.name,
                                arguments=tool_call.arguments,
                            )
                        )
                    error_result = ToolResult(
                        tool_name=tool_call.name,
                        output=error_text,
                        is_error=True,
                        metadata={
                            "arguments_parse_error": tool_call.arguments_error
                        },
                    )
                    append_tool_result(
                        loop_messages,
                        tool_call_id=tool_call.id,
                        result=error_result,
                    )
                    if session is not None:
                        await self.event_bus.emit(
                            ToolCallCompleted(
                                session=session,
                                iteration=iterations,
                                call_id=tool_call.id,
                                tool_name=tool_call.name,
                                arguments=tool_call.arguments,
                                final_arguments=tool_call.arguments,
                                status="invalid_arguments",
                                result_preview=error_text,
                            )
                        )
                    current_step["calls"].append(
                        {
                            "call_id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "status": "invalid_arguments",
                            "result": error_text,
                        }
                    )
                    await _publish_tool(
                        stream_sink,
                        activity_id,
                        tool_call.name,
                        "failed",
                    )
                    continue
                # ── 按需解锁：未解锁工具走 preflight + 引导回填（TD4 / R3.8）──
                # preflight 让 pre hook 链先看一眼（不调 invoker），给未来 loop guard
                # 留插座位；未被 deny 则回填"请先 tool_search(select:...) 解锁"引导。
                if (
                    visible_set is not None
                    and not visible_set.is_visible(tool_call.name)
                ):
                    preflight_result = await self.tool_executor.preflight(
                        ToolExecutionRequest(
                            tool_name=tool_call.name,
                            arguments=dict(tool_call.arguments),
                            call_id=tool_call.id,
                            source="passive",
                            tool_batch=tool_batch,
                            tool_batch_index=batch_index,
                        )
                    )
                    if preflight_result.status == "denied":
                        # pre hook 明确拒绝 -> 用 hook 给的 reason 回填
                        guide = (
                            preflight_result.output
                            if isinstance(preflight_result.output, str)
                            else str(preflight_result.output)
                        )
                        deferred_status = "denied"
                    else:
                        guide = _UNLOCK_GUIDE_TEMPLATE.format(name=tool_call.name)
                        deferred_status = "deferred"
                    if session is not None:
                        await self.event_bus.emit(
                            ToolCallStarted(
                                session=session,
                                iteration=iterations,
                                call_id=tool_call.id,
                                tool_name=tool_call.name,
                                arguments=tool_call.arguments,
                            )
                        )
                    guide_result = ToolResult(
                        tool_name=tool_call.name,
                        output=guide,
                        is_error=True,
                        metadata={"unlock_required": tool_call.name},
                    )
                    append_tool_result(
                        loop_messages,
                        tool_call_id=tool_call.id,
                        result=guide_result,
                    )
                    if session is not None:
                        await self.event_bus.emit(
                            ToolCallCompleted(
                                session=session,
                                iteration=iterations,
                                call_id=tool_call.id,
                                tool_name=tool_call.name,
                                arguments=tool_call.arguments,
                                final_arguments=tool_call.arguments,
                                status=deferred_status,
                                result_preview=guide,
                            )
                        )
                    current_step["calls"].append(
                        {
                            "call_id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "status": deferred_status,
                            "result": guide,
                            "pre_hook_trace": [
                                dict(t.__dict__)
                                for t in preflight_result.pre_hook_trace
                            ],
                        }
                    )
                    await _publish_tool(
                        stream_sink,
                        activity_id,
                        tool_call.name,
                        "failed",
                    )
                    continue

                if session is not None:
                    await self.event_bus.emit(
                        ToolCallStarted(
                            session=session,
                            iteration=iterations,
                            call_id=tool_call.id,
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                        )
                    )

                try:
                    execution = await self.tool_executor.execute(
                        ToolExecutionRequest(
                            tool_name=tool_call.name,
                            arguments=dict(tool_call.arguments),
                            call_id=tool_call.id,
                            source="passive",
                            tool_batch=tool_batch,
                            tool_batch_index=batch_index,
                        )
                    )
                except Exception:
                    await _publish_tool(
                        stream_sink,
                        activity_id,
                        tool_call.name,
                        "failed",
                    )
                    raise
                result = _as_tool_result(tool_call.name, execution)
                await _publish_tool(
                    stream_sink,
                    activity_id,
                    tool_call.name,
                    "completed" if execution.status == "success" else "failed",
                )
                await _check_cancelled(stream_sink)

                result_preview = self._preview_tool_result(result)
                if session is not None:
                    await self.event_bus.emit(
                        ToolCallCompleted(
                            session=session,
                            iteration=iterations,
                            call_id=tool_call.id,
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                            final_arguments=execution.final_arguments,
                            status=execution.status,
                            result_preview=result_preview,
                        )
                    )

                append_tool_result(
                    loop_messages,
                    tool_call_id=tool_call.id,
                    result=result,
                )
                # ── tool_search 解锁消费（TD3a/TD3b）──────────────────────
                if (
                    visible_set is not None
                    and tool_call.name == _TOOL_SEARCH_NAME
                    and execution.status == "success"
                ):
                    unlock_text = self._extract_unlock_text(result)
                    if unlock_text:
                        visible_set.consume_unlock_targets(unlock_text)
                if execution.status == "success":
                    tools_used.append(tool_call.name)
                invocations.append(tool_call)
                # tool_chain 记 final_arguments（post-hook 改参后的真实入参）+ hook trace，
                # 让回放能看到 ReadOnlyFilesystemHook 解析后的绝对路径等执行元数据（design 4.1）。
                call_meta = result.metadata if isinstance(result.metadata, dict) else {}
                current_step["calls"].append(
                    {
                        "call_id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": execution.final_arguments,
                        "status": execution.status,
                        "result": result_preview,
                        "pre_hook_trace": call_meta.get("pre_hook_trace", []),
                        "post_hook_trace": call_meta.get("post_hook_trace", []),
                    }
                )

                # ── Repeat guard ───────────────────────────────────────
                norm = json.dumps(
                    {"name": tool_call.name, "args": tool_call.arguments},
                    sort_keys=True,
                )
                repeat_history.append((tool_call.name, norm))
                if _detect_repeated_signature(repeat_history):
                    guard_tool_chain = [*tool_chain, current_step]
                    return ReasonerResult(
                        reply=self._render_incomplete_tool_loop_summary(guard_tool_chain),
                        tool_chain=guard_tool_chain,
                        invocations=invocations,
                        provider_raw=response.raw,
                        metadata={
                            "tools_used": tools_used,
                            "step_telemetry": step_telemetry,
                            "stop_reason": "repeated_tool_signature",
                            "react_stats": {
                                "iteration_count": iterations + 1,
                                "tools_used_count": len(tools_used),
                            },
                        },
                    )

            tool_chain.append(current_step)

            # ── after_step lifecycle gate ───────────────────────────────
            if self.after_step is not None:
                if session is None:  # pragma: no cover - defensive invariant
                    raise RuntimeError("reasoner after_step requires a structured session")
                after_step = await self.after_step.run(
                    AfterStepInput(
                        session=session,
                        iteration=iterations,
                        messages=loop_messages,
                        tool_chain=tool_chain,
                    )
                )
                if after_step.telemetry:
                    step_telemetry.append(dict(after_step.telemetry))
                if after_step.early_stop_reply is not None:
                    return ReasonerResult(
                        reply=after_step.early_stop_reply,
                        tool_chain=tool_chain,
                        invocations=invocations,
                        provider_raw=response.raw,
                        metadata={
                            "tools_used": tools_used,
                            "step_telemetry": step_telemetry,
                            "stop_reason": "after_step_early_stop",
                            "react_stats": {
                                "iteration_count": iterations + 1,
                                "tools_used_count": len(tools_used),
                            },
                        },
                    )
            iterations += 1

            if iterations >= self.max_tool_iterations:
                break

            # ── Next LLM round ─────────────────────────────────────────
            current_response = await self._chat_with_stream(
                loop_messages,
                tools=_current_schemas(),
                stream_sink=stream_sink,
            )

        # ── Incomplete: model still wants tools ─────────────────────────
        if current_response.tool_calls:
            summary = self._render_incomplete_tool_loop_summary(tool_chain)
            return ReasonerResult(
                reply=summary,
                tool_chain=tool_chain,
                invocations=invocations,
                provider_raw=response.raw,
                metadata={
                    "tools_used": tools_used,
                    "step_telemetry": step_telemetry,
                    "stop_reason": "max_iterations",
                    "react_stats": {
                        "iteration_count": iterations,
                        "tools_used_count": len(tools_used),
                    },
                },
            )

        # ── Normal exit — model replied without tool_calls ──────────────
        reply = current_response.content or ""
        return ReasonerResult(
            reply=reply,
            tool_chain=tool_chain,
            invocations=invocations,
            provider_raw=response.raw,
            metadata={
                "tools_used": tools_used,
                "step_telemetry": step_telemetry,
                "stop_reason": "completed",
                "react_stats": {
                    "iteration_count": iterations,
                    "tools_used_count": len(tools_used),
                },
            },
        )

    async def _chat_with_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        stream_sink: TurnStreamSink | None,
    ) -> LLMResponse:
        if stream_sink is None:
            return await self.provider.chat(messages, tools=tools)
        return await self.provider.chat(
            messages,
            tools=tools,
            content_sink=stream_sink.publish_content,
        )

    # ── internal helpers ────────────────────────────────────────────────────

    def _create_visible_set(self, session: SessionRef | None) -> TurnVisibleSet | None:
        if self.tool_registry is None:
            return None
        if session is None:
            raise ValueError("tool-enabled reasoner requires a structured session")
        visible_set = TurnVisibleSet(
            always_on=self.tool_registry.get_always_on_names(),
            discovery_state=self._discovery_store.for_session(session),
        )
        visible_set.warm_up_from_discovery()
        return visible_set

    def _schemas_for_visible_set(
        self, visible_set: TurnVisibleSet | None
    ) -> list[dict[str, Any]] | None:
        if self.tool_registry is None or visible_set is None:
            return None
        return self.tool_registry.get_schemas(names=visible_set.visible_names())

    @staticmethod
    def _preview_tool_result(result: Any) -> str:
        output = getattr(result, "output", result)
        if isinstance(output, str):
            return output
        try:
            return json.dumps(output, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(output)

    @staticmethod
    def _extract_unlock_text(result: Any) -> str:
        """从 tool_search 的 ToolResult 取出供 TurnVisibleSet 解锁的 JSON 文本。

        仅当 tool_search 走 select: 精确匹配路径（action=="select"）时才解锁——
        普通 search 返回候选列表但不应自动解锁（design 4.1：候选不等于授权）。
        tool_search 把候选列表 JSON 塞在 result.metadata['as_text']；
        action 塞在 result.output['action']。
        """
        output = getattr(result, "output", None)
        # 只对 select 路径解锁；普通 search 返回空
        if isinstance(output, dict) and output.get("action") != "select":
            return ""
        metadata = getattr(result, "metadata", None) or {}
        as_text = metadata.get("as_text") if isinstance(metadata, dict) else None
        if isinstance(as_text, str) and as_text:
            return as_text
        if isinstance(output, list):
            try:
                return json.dumps(output, ensure_ascii=False)
            except TypeError:
                return ""
        return ""

    @staticmethod
    def _render_incomplete_tool_loop_summary(
        tool_chain: list[dict[str, Any]],
    ) -> str:
        if not tool_chain:
            return "工具执行已经达到本轮上限，但还没有完成任何工具调用。请继续下一轮处理。"

        lines = ["工具执行已经达到本轮上限，当前只能先返回阶段性结果。"]
        lines.append("已经完成的工具调用：")
        for index, step in enumerate(tool_chain, start=1):
            calls = step.get("calls") or []
            for call in calls:
                lines.append(
                    "- "
                    f"第 {index} 轮 {call['name']} "
                    f"status={call['status']} "
                    f"args={call['arguments']} "
                    f"result={call['result']}"
                )
        lines.append("如果继续，下一步应该基于这些工具结果再次请求模型生成最终回复。")
        return "\n".join(lines)


def _detect_repeated_signature(
    history: list[tuple[str, str]],
) -> bool:
    """Detect repeated tool signatures within ``_REPEAT_GUARD_WINDOW``."""
    if len(history) < _REPEAT_GUARD_WINDOW:
        return False
    *_, w3, w2, w1, w0 = history[-_REPEAT_GUARD_WINDOW:]
    return w0 == w2 and w1 == w3


def _as_tool_result(tool_name: str, execution: ToolExecutionResult) -> ToolResult:
    """将执行边界的结构化结果渲染为 provider 所需的 tool message。"""
    if isinstance(execution.output, ToolResult):
        return ToolResult(
            tool_name=execution.output.tool_name or tool_name,
            output=execution.output.output,
            is_error=execution.output.is_error or execution.status != "success",
            metadata={
                **execution.output.metadata,
                "pre_hook_trace": [dict(t.__dict__) for t in execution.pre_hook_trace],
                "post_hook_trace": [dict(t.__dict__) for t in execution.post_hook_trace],
            },
        )
    return ToolResult(
        tool_name=tool_name,
        output=execution.output,
        is_error=execution.status != "success",
        metadata={
            "pre_hook_trace": [dict(t.__dict__) for t in execution.pre_hook_trace],
            "post_hook_trace": [dict(t.__dict__) for t in execution.post_hook_trace],
        },
    )
