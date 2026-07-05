from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias, cast

from amadeus.runtime.lifecycle import AfterStepContext, BeforeStepContext, TurnLifecycle
from amadeus.runtime.phase import PhaseFrame, PhaseModule, topo_sort_modules
from amadeus.session.identity import SessionRef

_BEFORE_CTX_SLOT = "step:before_ctx"
_AFTER_CTX_SLOT = "step:after_ctx"
_EXTRA_HINT_PREFIX = "step:extra_hint:"
_EARLY_STOP_SLOT = "step:early_stop_reply"
_TELEMETRY_PREFIX = "step:telemetry:"


@dataclass
class BeforeStepInput:
    session: SessionRef
    iteration: int
    messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]] | None


@dataclass
class AfterStepInput:
    session: SessionRef
    iteration: int
    messages: list[dict[str, Any]]
    tool_chain: list[dict[str, Any]]


@dataclass
class BeforeStepFrame(PhaseFrame[BeforeStepInput, BeforeStepContext]):
    pass


@dataclass
class AfterStepFrame(PhaseFrame[AfterStepInput, AfterStepContext]):
    pass


BeforeStepModules: TypeAlias = list[PhaseModule[BeforeStepFrame]]
AfterStepModules: TypeAlias = list[PhaseModule[AfterStepFrame]]


class _BuildBeforeStepCtxModule:
    slot = "before_step.build_ctx"
    produces = (_BEFORE_CTX_SLOT,)

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        frame.slots[_BEFORE_CTX_SLOT] = BeforeStepContext(
            session=frame.input.session,
            iteration=frame.input.iteration,
            messages=list(frame.input.messages),
            tool_schemas=frame.input.tool_schemas,
        )
        return frame


class _EmitBeforeStepCtxModule:
    slot = "before_step.emit"
    requires = ("before_step.build_ctx", _BEFORE_CTX_SLOT)
    produces = (_BEFORE_CTX_SLOT,)

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        context = cast(BeforeStepContext, frame.slots[_BEFORE_CTX_SLOT])
        frame.slots[_BEFORE_CTX_SLOT] = await self._lifecycle.before_step(context)
        return frame


class _CollectBeforeStepExportSlotsModule:
    slot = "before_step.collect_exports"
    requires = ("before_step.emit", _BEFORE_CTX_SLOT)
    produces = (_BEFORE_CTX_SLOT,)

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        context = cast(BeforeStepContext, frame.slots[_BEFORE_CTX_SLOT])
        context.extra_hints.extend(
            str(value)
            for slot, value in sorted(frame.slots.items())
            if slot.startswith(_EXTRA_HINT_PREFIX) and value is not None
        )
        early_stop = frame.slots.get(_EARLY_STOP_SLOT)
        if early_stop is not None:
            context.early_stop_reply = str(early_stop)
        frame.slots[_BEFORE_CTX_SLOT] = context
        return frame


class _ReturnBeforeStepCtxModule:
    slot = "before_step.return"
    requires = ("before_step.collect_exports", _BEFORE_CTX_SLOT)

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        frame.output = cast(BeforeStepContext, frame.slots[_BEFORE_CTX_SLOT])
        return frame


class _BuildAfterStepCtxModule:
    slot = "after_step.build_ctx"
    produces = (_AFTER_CTX_SLOT,)

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        frame.slots[_AFTER_CTX_SLOT] = AfterStepContext(
            session=frame.input.session,
            iteration=frame.input.iteration,
            messages=list(frame.input.messages),
            tool_chain=list(frame.input.tool_chain),
        )
        return frame


class _EmitAfterStepCtxModule:
    slot = "after_step.emit"
    requires = ("after_step.build_ctx", _AFTER_CTX_SLOT)
    produces = (_AFTER_CTX_SLOT,)

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        context = cast(AfterStepContext, frame.slots[_AFTER_CTX_SLOT])
        frame.slots[_AFTER_CTX_SLOT] = await self._lifecycle.after_step(context)
        return frame


class _CollectAfterStepExportSlotsModule:
    slot = "after_step.collect_exports"
    requires = ("after_step.emit", _AFTER_CTX_SLOT)
    produces = (_AFTER_CTX_SLOT,)

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        context = cast(AfterStepContext, frame.slots[_AFTER_CTX_SLOT])
        for slot, value in sorted(frame.slots.items()):
            if slot.startswith(_TELEMETRY_PREFIX):
                context.telemetry[slot.removeprefix(_TELEMETRY_PREFIX)] = value
        early_stop = frame.slots.get(_EARLY_STOP_SLOT)
        if early_stop is not None:
            context.early_stop_reply = str(early_stop)
        frame.slots[_AFTER_CTX_SLOT] = context
        return frame


class _ReturnAfterStepCtxModule:
    slot = "after_step.return"
    requires = ("after_step.collect_exports", _AFTER_CTX_SLOT)

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        frame.output = cast(AfterStepContext, frame.slots[_AFTER_CTX_SLOT])
        return frame


def default_before_step_modules(
    *,
    lifecycle: TurnLifecycle,
    plugin_modules: BeforeStepModules | None = None,
) -> BeforeStepModules:
    builtins: BeforeStepModules = [
        _BuildBeforeStepCtxModule(),
        _EmitBeforeStepCtxModule(lifecycle),
        _CollectBeforeStepExportSlotsModule(),
        _ReturnBeforeStepCtxModule(),
    ]
    return cast(BeforeStepModules, topo_sort_modules(builtins + list(plugin_modules or [])))


def default_after_step_modules(
    *,
    lifecycle: TurnLifecycle,
    plugin_modules: AfterStepModules | None = None,
) -> AfterStepModules:
    builtins: AfterStepModules = [
        _BuildAfterStepCtxModule(),
        _EmitAfterStepCtxModule(lifecycle),
        _CollectAfterStepExportSlotsModule(),
        _ReturnAfterStepCtxModule(),
    ]
    return cast(AfterStepModules, topo_sort_modules(builtins + list(plugin_modules or [])))
