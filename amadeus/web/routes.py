from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from amadeus.turns import TurnStore
from amadeus.web.dependencies import get_turn_store
from amadeus.web.schemas import (
    HealthResponse,
    MessageRequest,
    TurnResponse,
    turn_response,
)
from amadeus.web.sse import turn_event_stream

api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@api_router.post("/messages", response_model=TurnResponse)
async def create_message(
    payload: MessageRequest,
    store: Annotated[TurnStore, Depends(get_turn_store)],
) -> TurnResponse:
    session_key = (payload.session_key or "web:default").strip() or "web:default"
    turn = store.create_turn(
        session_key=session_key,
        content=payload.message,
        metadata={"channel": "web", **payload.metadata},
    )
    return turn_response(turn)


@api_router.get("/turns/{turn_id}", response_model=TurnResponse)
async def get_turn(
    turn_id: str,
    store: Annotated[TurnStore, Depends(get_turn_store)],
) -> TurnResponse:
    turn = store.get_turn(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return turn_response(turn)


@api_router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: str,
    store: Annotated[TurnStore, Depends(get_turn_store)],
) -> StreamingResponse:
    if store.get_turn(turn_id) is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return StreamingResponse(
        turn_event_stream(store, turn_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
