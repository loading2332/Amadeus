from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias, cast

from amadeus.context import ContextBuilder, ContextRenderResult, RuntimeContext
from amadeus.prompting import PromptSectionRender
from amadeus.runtime.lifecycle import PromptRenderContext, TurnLifecycle
from amadeus.runtime.phase import PhaseFrame, PhaseModule, topo_sort_modules
from amadeus.session.identity import SessionRef


@dataclass(frozen=True)
class PromptRenderInput:
    session: SessionRef
    attempt_index: int
    attempt_name: str
    runtime_context: RuntimeContext


@dataclass
class PromptRenderCtx:
    session: SessionRef
    attempt_index: int
    attempt_name: str
    runtime_context: RuntimeContext
    system_sections_top: list[PromptSectionRender] = field(default_factory=list)
    system_sections_bottom: list[PromptSectionRender] = field(default_factory=list)
    extra_hints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PromptRenderResult:
    messages: list[dict[str, object]]
    rendered: ContextRenderResult


@dataclass
class PromptRenderFrame(PhaseFrame[PromptRenderInput, PromptRenderResult]):
    pass


PromptRenderModules: TypeAlias = list[PhaseModule[PromptRenderFrame]]


_CTX_SLOT = "prompt:ctx"
_RESULT_SLOT = "prompt:result"
_SECTION_TOP_PREFIX = "prompt:section_top:"
_SECTION_BOTTOM_PREFIX = "prompt:section_bottom:"
_EXTRA_HINT_PREFIX = "prompt:extra_hint:"


class _BuildPromptRenderCtxModule:
    slot = "prompt_render.build_ctx"
    requires: tuple[str, ...] = ()
    produces = (_CTX_SLOT,)

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        input = frame.input
        frame.slots[_CTX_SLOT] = PromptRenderCtx(
            session=input.session,
            attempt_index=input.attempt_index,
            attempt_name=input.attempt_name,
            runtime_context=input.runtime_context,
        )
        return frame


class _EmitPromptRenderCtxModule:
    slot = "prompt_render.emit"
    requires = ("prompt_render.build_ctx", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        ctx = cast(PromptRenderCtx, frame.slots[_CTX_SLOT])
        emitted = await self._lifecycle.prompt_render(
            PromptRenderContext(
                session=ctx.session,
                attempt_index=ctx.attempt_index,
                attempt_name=ctx.attempt_name,
                runtime_context=ctx.runtime_context,
            )
        )
        ctx.runtime_context = emitted.runtime_context
        frame.slots[_CTX_SLOT] = ctx
        return frame


class _CollectPromptExportSlotsModule:
    slot = "prompt_render.collect_exports"
    requires = ("prompt_render.emit", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        ctx = cast(PromptRenderCtx, frame.slots[_CTX_SLOT])
        _append_sections(
            ctx.system_sections_top,
            _collect_prefixed_slots(frame.slots, _SECTION_TOP_PREFIX),
            priority=-1_000,
        )
        _append_sections(
            ctx.system_sections_bottom,
            _collect_prefixed_slots(frame.slots, _SECTION_BOTTOM_PREFIX),
            priority=8_000,
        )
        _append_string_exports(
            ctx.extra_hints,
            _collect_prefixed_slots(frame.slots, _EXTRA_HINT_PREFIX),
        )
        return frame


class _RenderPromptModule:
    slot = "prompt_render.render"
    requires = ("prompt_render.collect_exports", _CTX_SLOT)
    produces = (_RESULT_SLOT,)

    def __init__(self, context_builder: ContextBuilder) -> None:
        self._context_builder = context_builder

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        ctx = cast(PromptRenderCtx, frame.slots[_CTX_SLOT])
        original_context = ctx.runtime_context
        render_context = RuntimeContext(
            workspace_root=original_context.workspace_root,
            history=original_context.history,
            current_user_message=original_context.current_user_message,
            retrieved_memory=original_context.retrieved_memory,
            active_skills=list(original_context.active_skills),
            runtime_metadata=dict(original_context.runtime_metadata),
            recent_context_override=original_context.recent_context_override,
            disabled_sections=set(original_context.disabled_sections),
            turn_injection_context=dict(original_context.turn_injection_context),
            history_window=original_context.history_window,
        )
        render_context.turn_injection_context.update(
            {
                f"plugin_hint:{index}": hint
                for index, hint in enumerate(ctx.extra_hints)
            }
        )
        rendered = self._context_builder.render_with_sections(
            render_context,
            system_sections_top=ctx.system_sections_top,
            system_sections_bottom=ctx.system_sections_bottom,
        )
        frame.slots[_RESULT_SLOT] = PromptRenderResult(
            messages=[dict(message) for message in rendered.messages],
            rendered=rendered,
        )
        return frame


class _ReturnPromptRenderResultModule:
    slot = "prompt_render.return"
    requires = ("prompt_render.render", _RESULT_SLOT)

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        frame.output = cast(PromptRenderResult, frame.slots[_RESULT_SLOT])
        return frame


def default_prompt_render_modules(
    *,
    lifecycle: TurnLifecycle,
    context_builder: ContextBuilder,
    plugin_modules: PromptRenderModules | None = None,
) -> PromptRenderModules:
    builtins: PromptRenderModules = [
        _BuildPromptRenderCtxModule(),
        _EmitPromptRenderCtxModule(lifecycle),
        _CollectPromptExportSlotsModule(),
        _RenderPromptModule(context_builder),
        _ReturnPromptRenderResultModule(),
    ]
    return cast(
        PromptRenderModules,
        topo_sort_modules(builtins + list(plugin_modules or [])),
    )


def _collect_prefixed_slots(slots: dict[str, object], prefix: str) -> dict[str, object]:
    return {
        key.removeprefix(prefix): value
        for key, value in slots.items()
        if key.startswith(prefix)
    }


def _append_sections(
    target: list[PromptSectionRender],
    exports: dict[str, object],
    *,
    priority: int,
) -> None:
    for label, value in exports.items():
        if isinstance(value, PromptSectionRender):
            target.append(value)
        elif isinstance(value, str) and value.strip():
            target.append(
                PromptSectionRender(
                    label=label,
                    content=value,
                    priority=priority,
                    is_static=False,
                )
            )


def _append_string_exports(target: list[str], exports: dict[str, object]) -> None:
    for value in exports.values():
        if isinstance(value, str) and value.strip():
            target.append(value)
