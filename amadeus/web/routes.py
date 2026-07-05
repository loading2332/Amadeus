from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore
from amadeus.web.dependencies import get_session_store, get_turn_store
from amadeus.web.schemas import (
    HealthResponse,
    MessageRequest,
    MessageResponse,
    SessionCreateRequest,
    SessionResponse,
    TurnResponse,
    turn_response,
)
from amadeus.web.sse import turn_event_stream

api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@api_router.post("/sessions", response_model=SessionResponse)
async def create_session(
    payload: SessionCreateRequest,
    session_store: Annotated[PostgresSessionStore, Depends(get_session_store)],
) -> SessionResponse:
    row = session_store.create_session(
        user_id=payload.user_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    return SessionResponse(**row)


@api_router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    user_id: int,
    session_store: Annotated[PostgresSessionStore, Depends(get_session_store)],
) -> list[SessionResponse]:
    return [SessionResponse(**row) for row in session_store.list_sessions(user_id=user_id)]


@api_router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
)
async def list_messages(
    session_id: int,
    user_id: int,
    session_store: Annotated[PostgresSessionStore, Depends(get_session_store)],
) -> list[MessageResponse]:
    return [
        MessageResponse(**row)
        for row in session_store.list_messages(user_id=user_id, session_id=session_id)
    ]


@api_router.post("/messages", response_model=TurnResponse)
async def create_message(
    payload: MessageRequest,
    store: Annotated[PostgresTurnStore, Depends(get_turn_store)],
) -> TurnResponse:
    turn = store.create_turn(
        user_id=payload.user_id,
        session_id=payload.session_id,
        content=payload.message,
        metadata={"channel": "web", **payload.metadata},
    )
    return turn_response(turn)


@api_router.get("/turns/{turn_id}", response_model=TurnResponse)
async def get_turn(
    turn_id: str,
    store: Annotated[PostgresTurnStore, Depends(get_turn_store)],
) -> TurnResponse:
    turn = store.get_turn(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return turn_response(turn)


@api_router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: str,
    store: Annotated[PostgresTurnStore, Depends(get_turn_store)],
) -> StreamingResponse:
    if store.get_turn(turn_id) is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return StreamingResponse(
        turn_event_stream(store, turn_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
