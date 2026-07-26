from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from amadeus.turns import TERMINAL_TURN_STATUSES, PostgresTurnStore, TurnEvent


async def turn_event_stream(
    store: PostgresTurnStore,
    turn_id: str,
    *,
    after_seq: int = 0,
    poll_interval: float = 0.25,
    keepalive_interval: float = 15.0,
) -> AsyncIterator[str]:
    cursor = max(0, int(after_seq))
    last_keepalive = time.monotonic()
    while True:
        # store 是同步 psycopg 实现；下沉线程池避免阻塞事件循环。
        turn = await asyncio.to_thread(store.get_turn, turn_id)
        if turn is None:
            return
        events = await asyncio.to_thread(
            store.list_events, turn_id, after_seq=cursor
        )
        for event in events:
            yield _sse(event)
            cursor = event.seq
        if turn.status in TERMINAL_TURN_STATUSES:
            return
        now = time.monotonic()
        if now - last_keepalive >= keepalive_interval:
            yield ": keepalive\n\n"
            last_keepalive = now
        await asyncio.sleep(poll_interval)


def _sse(event: TurnEvent) -> str:
    payload = {
        "seq": event.seq,
        "type": event.type,
        "turn_id": event.turn_id,
        "occurred_at": event.occurred_at,
        "data": event.data,
    }
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event.seq}\nevent: turn_event\ndata: {data}\n\n"
