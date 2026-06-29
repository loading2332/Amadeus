from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from amadeus.after_reasoning import (
    AfterReasoningFrame,
    AfterReasoningInput,
    AfterReasoningModules,
    AfterReasoningResult,
    default_after_reasoning_modules,
)
from amadeus.after_turn import (
    AfterTurnFrame,
    AfterTurnInput,
    AfterTurnModules,
    default_after_turn_modules,
)
from amadeus.before_reasoning import (
    BeforeReasoningFrame,
    BeforeReasoningInput,
    BeforeReasoningModules,
    default_before_reasoning_modules,
)
from amadeus.before_turn import (
    BeforeTurnFrame,
    BeforeTurnInput,
    BeforeTurnModules,
    default_before_turn_modules,
)
from amadeus.context import ContextBuilder, ContextRenderResult, RuntimeContext
from amadeus.events import EventBus, ToolCallCompleted, ToolCallStarted
from amadeus.lifecycle import (
    AfterStepContext,
    AfterTurnContext,
    BeforeReasoningContext,
    BeforeStepContext,
    BeforeTurnContext,
    TurnLifecycle,
)
from amadeus.memory_engine import MemoryEngine
from amadeus.phase import Phase
from amadeus.prompt_render import (
    PromptRenderFrame,
    PromptRenderInput,
    PromptRenderModules,
    PromptRenderResult,
    default_prompt_render_modules,
)
from amadeus.prompting import build_context_trim_attempts
from amadeus.provider import ContextLengthError, LLMProvider, LLMResponse
from amadeus.session import Session, SessionManager
from amadeus.step_phases import (
    AfterStepFrame,
    AfterStepInput,
    AfterStepModules,
    BeforeStepFrame,
    BeforeStepInput,
    BeforeStepModules,
    default_after_step_modules,
    default_before_step_modules,
)
from amadeus.tool_runtime import (
    append_assistant_tool_calls,
    append_tool_result,
    tool_call_batch_snapshot,
)
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry
from amadeus.types import ReasonerResult


@dataclass(frozen=True)
class PassiveTurnResult:
    session_key: str
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    context: ContextRenderResult
    provider_raw: Any = None
    tool_chain: list[dict[str, Any]] = field(default_factory=list)
    context_retry: dict[str, Any] = field(default_factory=dict)


@dataclass
class PassiveRuntime:
    workspace_root: Path
    provider: LLMProvider
    session_manager: SessionManager
    event_bus: EventBus = field(default_factory=EventBus)
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)
    history_window: int = 500
    memory_engine: MemoryEngine | None = None
    tool_registry: ToolRegistry | None = None
    tool_executor: ToolExecutor | None = None
    max_tool_iterations: int = 10
    lifecycle: TurnLifecycle = field(init=False)
    _before_turn_plugin_modules: BeforeTurnModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _before_turn: Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame] = field(
        init=False,
        repr=False,
    )
    _prompt_render_plugin_modules: PromptRenderModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _prompt_render: Phase[PromptRenderInput, PromptRenderResult, PromptRenderFrame] = (
        field(
            init=False,
            repr=False,
        )
    )
    _before_reasoning_plugin_modules: BeforeReasoningModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _before_reasoning: Phase[
        BeforeReasoningInput,
        BeforeReasoningContext,
        BeforeReasoningFrame,
    ] = field(init=False, repr=False)
    _before_step_plugin_modules: BeforeStepModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _before_step: Phase[BeforeStepInput, BeforeStepContext, BeforeStepFrame] = field(
        init=False,
        repr=False,
    )
    _after_step_plugin_modules: AfterStepModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _after_step: Phase[AfterStepInput, AfterStepContext, AfterStepFrame] = field(
        init=False,
        repr=False,
    )
    _after_reasoning_plugin_modules: AfterReasoningModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _after_reasoning: Phase[
        AfterReasoningInput,
        AfterReasoningResult,
        AfterReasoningFrame,
    ] = field(init=False, repr=False)
    _after_turn_plugin_modules: AfterTurnModules = field(
        init=False,
        default_factory=list,
        repr=False,
    )
    _after_turn: Phase[AfterTurnInput, object, AfterTurnFrame] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.lifecycle = TurnLifecycle(self.event_bus)
        self._before_turn = self._build_before_turn_phase(
            self._before_turn_plugin_modules
        )
        self._prompt_render = self._build_prompt_render_phase(
            self._prompt_render_plugin_modules
        )
        self._before_reasoning = self._build_before_reasoning_phase(
            self._before_reasoning_plugin_modules
        )
        self._before_step = self._build_before_step_phase(
            self._before_step_plugin_modules
        )
        self._after_step = self._build_after_step_phase(self._after_step_plugin_modules)
        self._after_reasoning = self._build_after_reasoning_phase(
            self._after_reasoning_plugin_modules
        )
        self._after_turn = self._build_after_turn_phase(
            self._after_turn_plugin_modules
        )

    def set_before_turn_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(BeforeTurnModules, list(modules))
        candidate_phase = self._build_before_turn_phase(candidate_modules)
        self._before_turn_plugin_modules = candidate_modules
        self._before_turn = candidate_phase

    def set_prompt_render_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(PromptRenderModules, list(modules))
        candidate_phase = self._build_prompt_render_phase(candidate_modules)
        self._prompt_render_plugin_modules = candidate_modules
        self._prompt_render = candidate_phase

    def set_before_reasoning_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(BeforeReasoningModules, list(modules))
        candidate_phase = self._build_before_reasoning_phase(candidate_modules)
        self._before_reasoning_plugin_modules = candidate_modules
        self._before_reasoning = candidate_phase

    def set_before_step_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(BeforeStepModules, list(modules))
        candidate_phase = self._build_before_step_phase(candidate_modules)
        self._before_step_plugin_modules = candidate_modules
        self._before_step = candidate_phase

    def set_after_step_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(AfterStepModules, list(modules))
        candidate_phase = self._build_after_step_phase(candidate_modules)
        self._after_step_plugin_modules = candidate_modules
        self._after_step = candidate_phase

    def set_after_reasoning_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(AfterReasoningModules, list(modules))
        candidate_phase = self._build_after_reasoning_phase(candidate_modules)
        self._after_reasoning_plugin_modules = candidate_modules
        self._after_reasoning = candidate_phase

    def set_after_turn_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(AfterTurnModules, list(modules))
        candidate_phase = self._build_after_turn_phase(candidate_modules)
        self._after_turn_plugin_modules = candidate_modules
        self._after_turn = candidate_phase

    def _build_before_turn_phase(
        self,
        plugin_modules: BeforeTurnModules,
    ) -> Phase[BeforeTurnInput, BeforeTurnContext, BeforeTurnFrame]:
        return Phase(
            default_before_turn_modules(
                lifecycle=self.lifecycle,
                session_manager=self.session_manager,
                memory_engine=self.memory_engine,
                history_window=self.history_window,
                plugin_modules=plugin_modules,
            ),
            frame_factory=BeforeTurnFrame,
        )

    def _build_prompt_render_phase(
        self,
        plugin_modules: PromptRenderModules,
    ) -> Phase[PromptRenderInput, PromptRenderResult, PromptRenderFrame]:
        return Phase(
            default_prompt_render_modules(
                lifecycle=self.lifecycle,
                context_builder=self.context_builder,
                plugin_modules=plugin_modules,
            ),
            frame_factory=PromptRenderFrame,
        )

    def _build_before_reasoning_phase(
        self,
        plugin_modules: BeforeReasoningModules,
    ) -> Phase[BeforeReasoningInput, BeforeReasoningContext, BeforeReasoningFrame]:
        return Phase(
            default_before_reasoning_modules(
                lifecycle=self.lifecycle,
                plugin_modules=plugin_modules,
            ),
            frame_factory=BeforeReasoningFrame,
        )

    def _build_before_step_phase(
        self,
        plugin_modules: BeforeStepModules,
    ) -> Phase[BeforeStepInput, BeforeStepContext, BeforeStepFrame]:
        return Phase(
            default_before_step_modules(
                lifecycle=self.lifecycle,
                plugin_modules=plugin_modules,
            ),
            frame_factory=BeforeStepFrame,
        )

    def _build_after_step_phase(
        self,
        plugin_modules: AfterStepModules,
    ) -> Phase[AfterStepInput, AfterStepContext, AfterStepFrame]:
        return Phase(
            default_after_step_modules(
                lifecycle=self.lifecycle,
                plugin_modules=plugin_modules,
            ),
            frame_factory=AfterStepFrame,
        )

    def _build_after_reasoning_phase(
        self,
        plugin_modules: AfterReasoningModules,
    ) -> Phase[AfterReasoningInput, AfterReasoningResult, AfterReasoningFrame]:
        return Phase(
            default_after_reasoning_modules(
                lifecycle=self.lifecycle,
                session_manager=self.session_manager,
                event_bus=self.event_bus,
                plugin_modules=plugin_modules,
            ),
            frame_factory=AfterReasoningFrame,
        )

    def _build_after_turn_phase(
        self,
        plugin_modules: AfterTurnModules,
    ) -> Phase[AfterTurnInput, object, AfterTurnFrame]:
        return Phase(
            default_after_turn_modules(
                lifecycle=self.lifecycle,
                plugin_modules=plugin_modules,
            ),
            frame_factory=AfterTurnFrame,
        )

    async def run_turn(
        self,
        *,
        session_key: str,
        user_message: str,
        retrieved_memory: str | None = None,
        active_skills: list[str] | None = None,
        runtime_metadata: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> PassiveTurnResult:
        before_turn_context = await self._before_turn.run(
            BeforeTurnInput(
                session_key=session_key,
                user_message=user_message,
                retrieved_memory=retrieved_memory,
                active_skills=tuple(active_skills or ()),
                runtime_metadata=dict(runtime_metadata or {}),
            )
        )
        if before_turn_context.abort_reply is not None:
            abort_rendered = self.context_builder.render(
                RuntimeContext(
                    workspace_root=self.workspace_root,
                    history=before_turn_context.history,
                    current_user_message=user_message,
                    retrieved_memory=before_turn_context.retrieved_memory,
                    active_skills=before_turn_context.active_skills,
                    runtime_metadata=before_turn_context.runtime_metadata,
                    turn_injection_context=_hint_injection_context(
                        before_turn_context.extra_hints
                    ),
                )
            )
            return await self._complete_turn(
                session_key=session_key,
                user_message=user_message,
                assistant_content=before_turn_context.abort_reply,
                rendered=abort_rendered,
                provider_raw=None,
                tool_chain=[],
                context_retry={
                    "attempts": [],
                    "selected_plan": "before_turn_abort",
                    "trimmed_sections": [],
                },
                extra=extra,
            )

        before_reasoning_context = await self._before_reasoning.run(
            BeforeReasoningInput(before_turn=before_turn_context)
        )
        if before_reasoning_context.abort_reply is not None:
            abort_rendered = self.context_builder.render(
                RuntimeContext(
                    workspace_root=self.workspace_root,
                    history=before_reasoning_context.history,
                    current_user_message=user_message,
                    retrieved_memory=before_reasoning_context.retrieved_memory,
                    active_skills=before_reasoning_context.active_skills,
                    runtime_metadata=before_reasoning_context.runtime_metadata,
                    turn_injection_context=_hint_injection_context(
                        before_reasoning_context.extra_hints
                    ),
                )
            )
            return await self._complete_turn(
                session_key=session_key,
                user_message=user_message,
                assistant_content=before_reasoning_context.abort_reply,
                rendered=abort_rendered,
                provider_raw=None,
                tool_chain=[],
                context_retry={
                    "attempts": [],
                    "selected_plan": "before_reasoning_abort",
                    "trimmed_sections": [],
                },
                extra=extra,
            )
        session = self.session_manager.get_or_create(session_key)
        history = before_reasoning_context.history
        resolved_retrieved_memory = before_reasoning_context.retrieved_memory
        resolved_active_skills = before_reasoning_context.active_skills
        resolved_runtime_metadata = before_reasoning_context.runtime_metadata
        resolved_extra_hints = before_reasoning_context.extra_hints

        tool_schemas = (
            self.tool_registry.export_openai_tools() if self.tool_registry is not None else None
        )
        tool_chain: list[dict[str, Any]] = []
        provider_raw: Any = None
        assistant_content: str
        rendered: ContextRenderResult | None = None
        context_retry: dict[str, Any] = {
            "attempts": [],
            "selected_plan": None,
            "trimmed_sections": [],
        }

        attempts = build_context_trim_attempts(len(history))
        for attempt_index, attempt in enumerate(attempts):
            context_retry["attempts"].append(
                {
                    "name": attempt.name,
                    "history_window": attempt.history_window,
                    "disabled_sections": sorted(attempt.disabled_sections),
                }
            )
            context = RuntimeContext(
                workspace_root=self.workspace_root,
                history=history,
                current_user_message=user_message,
                retrieved_memory=resolved_retrieved_memory,
                active_skills=resolved_active_skills,
                runtime_metadata=resolved_runtime_metadata,
                disabled_sections=set(attempt.disabled_sections),
                history_window=attempt.history_window,
                turn_injection_context=_hint_injection_context(resolved_extra_hints),
            )
            prompt_render = await self._prompt_render.run(
                PromptRenderInput(
                    session_key=session_key,
                    attempt_index=attempt_index,
                    attempt_name=attempt.name,
                    runtime_context=context,
                )
            )
            rendered = prompt_render.rendered
            messages = [dict(message) for message in prompt_render.messages]
            try:
                response = await self.provider.chat(messages, tools=tool_schemas)
                provider_raw = response.raw
                if response.tool_calls:
                    reasoner_result = await self._run_tool_loop(
                        messages=messages,
                        response=response,
                        tool_schemas=tool_schemas,
                        session_key=session_key,
                    )
                    assistant_content = reasoner_result.reply
                    tool_chain = reasoner_result.tool_chain
                else:
                    if response.content is None:
                        raise ValueError("LLM response did not include assistant content")
                    assistant_content = response.content
                context_retry["selected_plan"] = attempt.name
                context_retry["trimmed_sections"] = sorted(attempt.disabled_sections)
                if attempt_index > 0:
                    self._trim_session_history(session, attempt.history_window)
                break
            except ContextLengthError:
                continue
        else:
            assistant_content = "上下文过长无法处理，请尝试新建对话。"
            if rendered is None:
                context = RuntimeContext(
                    workspace_root=self.workspace_root,
                    history=history,
                    current_user_message=user_message,
                    retrieved_memory=resolved_retrieved_memory,
                    active_skills=resolved_active_skills,
                    runtime_metadata=resolved_runtime_metadata,
                )
                rendered = self.context_builder.render(context)

        if rendered is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("runtime did not render prompt context")
        return await self._complete_turn(
            session_key=session_key,
            user_message=user_message,
            assistant_content=assistant_content,
            rendered=rendered,
            provider_raw=provider_raw,
            tool_chain=tool_chain,
            context_retry=context_retry,
            extra=extra,
        )

    async def _complete_turn(
        self,
        *,
        session_key: str,
        user_message: str,
        assistant_content: str,
        rendered: ContextRenderResult,
        provider_raw: Any,
        tool_chain: list[dict[str, Any]],
        context_retry: dict[str, Any],
        extra: dict[str, Any] | None,
    ) -> PassiveTurnResult:
        after_reasoning = await self._after_reasoning.run(
            AfterReasoningInput(
                session_key=session_key,
                user_message=user_message,
                assistant_content=assistant_content,
                rendered=rendered,
                provider_raw=provider_raw,
                tool_chain=tool_chain,
                context_retry=context_retry,
                extra=dict(extra or {}),
            )
        )
        result = PassiveTurnResult(
            session_key=after_reasoning.session_key,
            user_message_id=after_reasoning.user_message_id,
            assistant_message_id=after_reasoning.assistant_message_id,
            assistant_response=after_reasoning.assistant_response,
            context=after_reasoning.context,
            provider_raw=after_reasoning.provider_raw,
            tool_chain=after_reasoning.tool_chain,
            context_retry=after_reasoning.context_retry,
        )
        await self._after_turn.run(
            AfterTurnInput(
                context=AfterTurnContext(
                    session_key=session_key,
                    user_message_id=result.user_message_id,
                    assistant_message_id=result.assistant_message_id,
                    assistant_response=result.assistant_response,
                    tool_chain=tuple(dict(step) for step in result.tool_chain),
                    context_retry=dict(result.context_retry),
                )
            )
        )
        return result

    def _trim_session_history(self, session: Session, history_window: int) -> None:
        if history_window <= 0:
            session.messages.clear()
        else:
            session.messages = session.messages[-history_window:]
        session.last_consolidated = 0

    async def _run_tool_loop(
        self,
        *,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        tool_schemas: list[dict[str, Any]] | None,
        session_key: str = "",
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

        while current_response.tool_calls:
            if iterations >= self.max_tool_iterations:
                break

            before_step = await self._before_step.run(
                BeforeStepInput(
                    session_key=session_key,
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
                    metadata={
                        "tools_used": tools_used,
                        "step_telemetry": step_telemetry,
                        "react_stats": {
                            "iteration_count": iterations,
                            "tools_used_count": len(tools_used),
                        },
                    },
                )

            # 1. Batch snapshot → 注入每个 ToolExecutionRequest
            tool_batch = tool_call_batch_snapshot(current_response.tool_calls)

            # 2. Append assistant tool call message
            append_assistant_tool_calls(
                loop_messages,
                content=current_response.content,
                tool_calls=current_response.tool_calls,
            )

            # 3. Execute tool calls in this batch
            current_step: dict[str, Any] = {
                "text": current_response.content or "",
                "calls": [],
            }
            for batch_index, tool_call in enumerate(current_response.tool_calls):
                # Emit ToolCallStarted
                if session_key:
                    await self.event_bus.emit(
                        ToolCallStarted(
                            session_key=session_key,
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
                # Emit ToolCallCompleted
                if session_key:
                    await self.event_bus.emit(
                        ToolCallCompleted(
                            session_key=session_key,
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
            tool_chain.append(current_step)
            after_step = await self._after_step.run(
                AfterStepInput(
                    session_key=session_key,
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
                    metadata={
                        "tools_used": tools_used,
                        "step_telemetry": step_telemetry,
                        "react_stats": {
                            "iteration_count": iterations + 1,
                            "tools_used_count": len(tools_used),
                        },
                    },
                )
            iterations += 1

            if iterations >= self.max_tool_iterations:
                break

            # 4. Next LLM round
            current_response = await self.provider.chat(loop_messages, tools=tool_schemas)

        # 5. If loop ended due to tool_calls still present → incomplete summary
        if current_response.tool_calls:
            summary = self._render_incomplete_tool_loop_summary(tool_chain)
            return ReasonerResult(
                reply=summary,
                tool_chain=tool_chain,
                invocations=invocations,
                metadata={
                    "tools_used": tools_used,
                    "step_telemetry": step_telemetry,
                    "react_stats": {
                        "iteration_count": iterations,
                        "tools_used_count": len(tools_used),
                    },
                },
            )

        # 6. Normal exit — model replied without tool_calls
        reply = current_response.content or ""
        return ReasonerResult(
            reply=reply,
            tool_chain=tool_chain,
            invocations=invocations,
            metadata={
                "tools_used": tools_used,
                "step_telemetry": step_telemetry,
                "react_stats": {
                    "iteration_count": iterations,
                    "tools_used_count": len(tools_used),
                },
            },
        )

    def _render_incomplete_tool_loop_summary(
        self,
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

    def _preview_tool_result(self, result: Any) -> str:
        output = getattr(result, "output", result)
        if isinstance(output, str):
            return output
        try:
            return json.dumps(output, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(output)


def _hint_injection_context(hints: list[str]) -> dict[str, str]:
    return {f"lifecycle_hint_{index}": hint for index, hint in enumerate(hints)}
