from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from amadeus.web.dependencies import get_owner_scope
from amadeus.web.owner import OwnerScope, web_turn_metadata
from amadeus.web.schemas import (
    BootstrapResponse,
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


@api_router.get("/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> BootstrapResponse:
    return BootstrapResponse(owner_user_id=scope.user_id)


@api_router.post("/sessions", response_model=SessionResponse)
async def create_session(
    payload: SessionCreateRequest,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> SessionResponse:
    row = scope.session_store.create_session(
        user_id=scope.user_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    return SessionResponse(**row)


@api_router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> list[SessionResponse]:
    return [
        SessionResponse(**row)
        for row in scope.session_store.list_sessions(user_id=scope.user_id)
    ]


@api_router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
)
async def list_messages(
    session_id: int,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> list[MessageResponse]:
    session = scope.require_session(session_id)
    return [
        MessageResponse(**row)
        for row in scope.session_store.fetch_session_messages(session)
    ]


@api_router.post("/messages", response_model=TurnResponse)
async def create_message(
    payload: MessageRequest,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> TurnResponse:
    session = scope.require_session(payload.session_id)
    turn = scope.turn_store.create_turn(
        user_id=session.user_id,
        session_id=payload.session_id,
        content=payload.message,
        metadata=web_turn_metadata(payload.metadata),
    )
    return turn_response(turn)


@api_router.get("/turns/{turn_id}", response_model=TurnResponse)
async def get_turn(
    turn_id: str,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> TurnResponse:
    return turn_response(scope.require_turn(turn_id))


@api_router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: str,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> StreamingResponse:
    scope.require_turn(turn_id)
    return StreamingResponse(
        turn_event_stream(scope.turn_store, turn_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
