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
from amadeus.runtime.tool_runtime import (
    append_assistant_tool_calls,
    append_tool_result,
    tool_call_batch_snapshot,
)
from amadeus.session.identity import SessionRef
from amadeus.tools.executor import ToolExecutor
from amadeus.types import ReasonerResult

_REPEAT_GUARD_WINDOW = 4


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
        tool_schemas: Sequence[dict[str, Any]] | None = None,
        session: SessionRef | None = None,
    ) -> ReasonerResult:
        """Run a reasoning turn: provider call → optional tool loop → result."""
        response = await self.provider.chat(
            list(messages),
            tools=list(tool_schemas) if tool_schemas is not None else None,
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
            tool_schemas=list(tool_schemas) if tool_schemas is not None else None,
            session=session,
        )

    async def _run_tool_loop(
        self,
        *,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        tool_schemas: list[dict[str, Any]] | None,
        session: SessionRef | None = None,
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

        while current_response.tool_calls:
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
                        tool_schemas=tool_schemas,
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
                if session is not None:
                    await self.event_bus.emit(
                        ToolCallStarted(
                            session_key=session.session_key,
                            iteration=iterations,
                            call_id=tool_call.id,
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                        )
                    )

                result, trace = await self.tool_executor.execute_async(
                    tool_call.name,
                    tool_call.arguments,
                    call_id=tool_call.id,
                    tool_batch=tool_batch,
                    tool_batch_index=batch_index,
                )

                result_preview = self._preview_tool_result(result)
                if session is not None:
                    await self.event_bus.emit(
                        ToolCallCompleted(
                            session_key=session.session_key,
                            iteration=iterations,
                            call_id=tool_call.id,
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                            final_arguments=tool_call.arguments,
                            status=trace.status,
                            result_preview=result_preview,
                        )
                    )

                append_tool_result(
                    loop_messages,
                    tool_call_id=tool_call.id,
                    result=result,
                )
                if trace.status == "success":
                    tools_used.append(tool_call.name)
                invocations.append(tool_call)
                current_step["calls"].append(
                    {
                        "call_id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "status": trace.status,
                        "result": result_preview,
                    }
                )

                # ── Repeat guard ───────────────────────────────────────
                norm = json.dumps({"name": tool_call.name, "args": tool_call.arguments}, sort_keys=True)
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
            current_response = await self.provider.chat(loop_messages, tools=tool_schemas)

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

    # ── internal helpers ────────────────────────────────────────────────────

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
