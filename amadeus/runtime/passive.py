from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from amadeus.context import ContextBuilder, ContextRenderResult, RuntimeContext
from amadeus.events import EventBus
from amadeus.memory.engine import MemoryEngine
from amadeus.prompt_render import (
    PromptRenderFrame,
    PromptRenderInput,
    PromptRenderModules,
    PromptRenderResult,
    default_prompt_render_modules,
)
from amadeus.prompting import build_context_trim_attempts
from amadeus.provider import ContextLengthError, LLMProvider
from amadeus.runtime.after_reasoning import (
    AfterReasoningFrame,
    AfterReasoningInput,
    AfterReasoningModules,
    AfterReasoningResult,
    default_after_reasoning_modules,
)
from amadeus.runtime.after_turn import (
    AfterTurnFrame,
    AfterTurnInput,
    AfterTurnModules,
    AfterTurnResult,
    default_after_turn_modules,
)
from amadeus.runtime.before_reasoning import (
    BeforeReasoningFrame,
    BeforeReasoningInput,
    BeforeReasoningModules,
    default_before_reasoning_modules,
)
from amadeus.runtime.before_turn import (
    BeforeTurnFrame,
    BeforeTurnInput,
    BeforeTurnModules,
    default_before_turn_modules,
)
from amadeus.runtime.lifecycle import (
    AfterStepContext,
    AfterTurnContext,
    BeforeReasoningContext,
    BeforeStepContext,
    BeforeTurnContext,
    TurnLifecycle,
)
from amadeus.runtime.phase import Phase
from amadeus.runtime.reasoner import Reasoner
from amadeus.runtime.step_phases import (
    AfterStepFrame,
    AfterStepInput,
    AfterStepModules,
    BeforeStepFrame,
    BeforeStepInput,
    BeforeStepModules,
    default_after_step_modules,
    default_before_step_modules,
)
from amadeus.session.identity import SessionRef
from amadeus.session.store import Session, SessionManager
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


@dataclass(frozen=True)
class PassiveTurnResult:
    session: SessionRef
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    context: ContextRenderResult
    provider_raw: Any = None
    tool_chain: list[dict[str, Any]] = field(default_factory=list)
    context_retry: dict[str, Any] = field(default_factory=dict)
    memory_trace: dict[str, Any] = field(default_factory=dict)


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
    reasoner: Reasoner = field(init=False)
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
    _after_turn: Phase[AfterTurnInput, AfterTurnResult, AfterTurnFrame] = field(
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
        # Reasoner needs the built step phases — build it last
        self.reasoner = Reasoner(
            provider=self.provider,
            tool_executor=self.tool_executor,
            max_tool_iterations=self.max_tool_iterations,
            event_bus=self.event_bus,
            before_step=self._before_step,
            after_step=self._after_step,
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
        self.reasoner.before_step = candidate_phase

    def set_after_step_plugin_modules(self, modules: list[object]) -> None:
        candidate_modules = cast(AfterStepModules, list(modules))
        candidate_phase = self._build_after_step_phase(candidate_modules)
        self._after_step_plugin_modules = candidate_modules
        self._after_step = candidate_phase
        self.reasoner.after_step = candidate_phase

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
    ) -> Phase[AfterTurnInput, AfterTurnResult, AfterTurnFrame]:
        return Phase(
            default_after_turn_modules(
                lifecycle=self.lifecycle,
                memory_engine=self.memory_engine,
                session_manager=self.session_manager,
                plugin_modules=plugin_modules,
            ),
            frame_factory=AfterTurnFrame,
        )

    async def run_turn(
        self,
        *,
        session: SessionRef,
        user_message: str,
        retrieved_memory: str | None = None,
        active_skills: list[str] | None = None,
        runtime_metadata: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> PassiveTurnResult:
        before_turn_context = await self._before_turn.run(
            BeforeTurnInput(
                session=session,
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
                session=session,
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
                memory_trace=dict(before_turn_context.memory_trace),
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
                session=session,
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
                memory_trace=dict(before_reasoning_context.memory_trace),
                extra=extra,
            )
        runtime_session = self.session_manager.get_or_create(session)
        history = before_reasoning_context.history
        resolved_retrieved_memory = before_reasoning_context.retrieved_memory
        resolved_memory_trace = before_reasoning_context.memory_trace
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
                    session=session,
                    attempt_index=attempt_index,
                    attempt_name=attempt.name,
                    runtime_context=context,
                )
            )
            rendered = prompt_render.rendered
            messages = [dict(message) for message in prompt_render.messages]
            try:
                reasoner_result = await self.reasoner.reason(
                    messages=messages,
                    tool_schemas=tool_schemas,
                    session=session,
                )
                assistant_content = reasoner_result.reply
                tool_chain = reasoner_result.tool_chain
                provider_raw = reasoner_result.provider_raw
                context_retry["selected_plan"] = attempt.name
                context_retry["trimmed_sections"] = sorted(attempt.disabled_sections)
                if attempt_index > 0:
                    self._trim_session_history(runtime_session, attempt.history_window)
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
            session=session,
            user_message=user_message,
            assistant_content=assistant_content,
            rendered=rendered,
            provider_raw=provider_raw,
            tool_chain=tool_chain,
            context_retry=context_retry,
            memory_trace=dict(resolved_memory_trace),
            extra=extra,
        )

    async def _complete_turn(
        self,
        *,
        session: SessionRef,
        user_message: str,
        assistant_content: str,
        rendered: ContextRenderResult,
        provider_raw: Any,
        tool_chain: list[dict[str, Any]],
        context_retry: dict[str, Any],
        memory_trace: dict[str, Any],
        extra: dict[str, Any] | None,
    ) -> PassiveTurnResult:
        after_reasoning = await self._after_reasoning.run(
            AfterReasoningInput(
                session=session,
                user_message=user_message,
                assistant_content=assistant_content,
                rendered=rendered,
                provider_raw=provider_raw,
                tool_chain=tool_chain,
                context_retry=context_retry,
                extra=dict(extra or {}),
            )
        )
        after_turn_context = AfterTurnContext(
            session=session,
            user_message_id=after_reasoning.user_message_id,
            assistant_message_id=after_reasoning.assistant_message_id,
            assistant_response=after_reasoning.assistant_response,
            tool_chain=tuple(dict(step) for step in after_reasoning.tool_chain),
            context_retry=dict(after_reasoning.context_retry),
            memory_trace=dict(memory_trace),
        )
        after_turn_result = await self._after_turn.run(
            AfterTurnInput(
                context=after_turn_context
            )
        )
        return PassiveTurnResult(
            session=after_reasoning.session,
            user_message_id=after_reasoning.user_message_id,
            assistant_message_id=after_reasoning.assistant_message_id,
            assistant_response=after_reasoning.assistant_response,
            context=after_reasoning.context,
            provider_raw=after_reasoning.provider_raw,
            tool_chain=after_reasoning.tool_chain,
            context_retry=after_reasoning.context_retry,
            memory_trace=dict(after_turn_result.context.memory_trace),
        )

    def _trim_session_history(self, session: Session, history_window: int) -> None:
        if history_window <= 0:
            session.messages.clear()
        else:
            session.messages = session.messages[-history_window:]
        session.last_consolidated = 0


def _hint_injection_context(hints: list[str]) -> dict[str, str]:
    return {f"lifecycle_hint_{index}": hint for index, hint in enumerate(hints)}
