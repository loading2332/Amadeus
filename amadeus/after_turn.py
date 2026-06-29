from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias, cast

from amadeus.lifecycle import AfterTurnContext, TurnLifecycle
from amadeus.phase import PhaseFrame, PhaseModule, topo_sort_modules


@dataclass
class AfterTurnInput:
    context: AfterTurnContext


@dataclass(frozen=True)
class AfterTurnResult:
    context: AfterTurnContext


@dataclass
class AfterTurnFrame(PhaseFrame[AfterTurnInput, AfterTurnResult]):
    pass


AfterTurnModules: TypeAlias = list[PhaseModule[AfterTurnFrame]]


class _EmitAfterTurnCtxModule:
    slot = "after_turn.emit"

    def __init__(self, lifecycle: TurnLifecycle) -> None:
        self._lifecycle = lifecycle

    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        await self._lifecycle.after_turn(frame.input.context)
        return frame


class _ReturnAfterTurnResultModule:
    slot = "after_turn.return"
    requires = ("after_turn.emit",)

    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        frame.output = AfterTurnResult(context=frame.input.context)
        return frame


def default_after_turn_modules(
    *,
    lifecycle: TurnLifecycle,
    plugin_modules: AfterTurnModules | None = None,
) -> AfterTurnModules:
    builtins: AfterTurnModules = [
        _EmitAfterTurnCtxModule(lifecycle),
        _ReturnAfterTurnResultModule(),
    ]
    return cast(
        AfterTurnModules,
        topo_sort_modules(builtins + list(plugin_modules or [])),
    )
