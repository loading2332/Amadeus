from __future__ import annotations

import asyncio
from types import SimpleNamespace

from amadeus.turns import TurnEvent
from amadeus.web.sse import turn_event_stream


class _TerminalRaceStore:
    def __init__(self) -> None:
        self.terminal_written = False

    def get_turn(self, turn_id: str):
        return SimpleNamespace(
            status="done" if self.terminal_written else "processing"
        )

    def list_events(self, turn_id: str, *, after_seq: int = 0) -> list[TurnEvent]:
        if after_seq == 0:
            self.terminal_written = True
            return [
                TurnEvent(
                    turn_id=turn_id,
                    seq=1,
                    type="content_snapshot",
                    data={"content": "A", "version": 1},
                    occurred_at="2026-07-18T00:00:00+00:00",
                )
            ]
        return [
            TurnEvent(
                turn_id=turn_id,
                seq=2,
                type="turn_terminal",
                data={"status": "done"},
                occurred_at="2026-07-18T00:00:01+00:00",
            )
        ]


def test_sse_drains_terminal_event_written_during_poll() -> None:
    async def collect() -> str:
        chunks = [
            chunk
            async for chunk in turn_event_stream(
                _TerminalRaceStore(),  # type: ignore[arg-type]
                "turn-1",
                poll_interval=0,
            )
        ]
        return "".join(chunks)

    body = asyncio.run(collect())

    assert '"type": "content_snapshot"' in body
    assert '"type": "turn_terminal"' in body
    assert "id: 2\n" in body
