from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from amadeus.turns import TERMINAL_TURN_STATUSES, TurnStore
from amadeus.web.schemas import turn_response


async def turn_event_stream(
    store: TurnStore,
    turn_id: str,
    *,
    poll_interval: float = 0.75,
) -> AsyncIterator[str]:
    last_payload = ""
    while True:
        turn = store.get_turn(turn_id)
        if turn is None:
            payload: dict[str, Any] = {
                "turn_id": turn_id,
                "session_key": "",
                "user_id": None,
                "session_id": None,
                "status": "failed",
                "answer": None,
                "error": "Turn not found",
                "metadata": {},
                "created_at": None,
                "updated_at": None,
                "started_at": None,
                "finished_at": None,
            }
            yield _sse("failed", payload)
            return
        response = turn_response(turn).model_dump()
        encoded = json.dumps(response, ensure_ascii=False, sort_keys=True)
        if encoded != last_payload:
            yield _sse(turn.status, response)
            last_payload = encoded
        if turn.status in TERMINAL_TURN_STATUSES:
            return
        await asyncio.sleep(poll_interval)


def _sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"
