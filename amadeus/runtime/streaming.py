from __future__ import annotations

from typing import Protocol


class TurnCancelled(Exception):
    """Cooperative cancellation requested for the active turn."""


class TurnStreamSink(Protocol):
    async def publish_content(self, delta: str) -> None: ...

    async def publish_tool_activity(
        self,
        *,
        activity_id: str,
        tool_name: str,
        state: str,
    ) -> None: ...

    async def check_cancelled(self) -> None: ...

    async def begin_finalization(self) -> None: ...
