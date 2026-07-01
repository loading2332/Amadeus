from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias, cast

from amadeus.memory.engine import MemoryEngine
from amadeus.runtime.lifecycle import AfterTurnContext, TurnLifecycle
from amadeus.runtime.phase import PhaseFrame, PhaseModule, topo_sort_modules
from amadeus.session.store import SessionManager


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
    requires = ("after_turn.post_response",)

    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        frame.output = AfterTurnResult(context=frame.input.context)
        return frame


class _RunPostResponseMemoryModule:
    slot = "after_turn.post_response"
    requires = ("after_turn.emit",)

    def __init__(
        self,
        memory_engine: MemoryEngine | None,
        session_manager: SessionManager,
    ) -> None:
        self._memory_engine = memory_engine
        self._session_manager = session_manager

    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        if self._memory_engine is None:
            return frame
        session_key = frame.input.context.session_key
        session = self._session_manager.get_or_create(session_key)
        try:
            trace = await self._memory_engine.run_post_response(
                session_key=session_key,
                messages=list(session.messages),
                explicit_memory_ids=list(
                    frame.input.context.memory_trace.get("explicit_memory_ids", [])
                ),
            )
        except Exception as error:
            trace = {
                "status": "error",
                "reason": "post_response_worker_failed",
                "error": str(error),
            }
        frame.input.context.memory_trace["post_response"] = trace
        return frame


def default_after_turn_modules(
    *,
    lifecycle: TurnLifecycle,
    memory_engine: MemoryEngine | None,
    session_manager: SessionManager,
    plugin_modules: AfterTurnModules | None = None,
) -> AfterTurnModules:
    builtins: AfterTurnModules = [
        _EmitAfterTurnCtxModule(lifecycle),
        _RunPostResponseMemoryModule(memory_engine, session_manager),
        _ReturnAfterTurnResultModule(),
    ]
    return cast(
        AfterTurnModules,
        topo_sort_modules(builtins + list(plugin_modules or [])),
    )
