from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
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

# 各路由的 store 均为同步 psycopg 实现；async 路由内统一经
# asyncio.to_thread 下沉线程池，避免阻塞事件循环（连接池为
# psycopg_pool.ConnectionPool，线程安全）。

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
    row = await asyncio.to_thread(
        scope.session_store.create_session,
        user_id=scope.user_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    return SessionResponse(**row)


@api_router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> list[SessionResponse]:
    rows = await asyncio.to_thread(
        scope.session_store.list_sessions,
        user_id=scope.user_id,
    )
    return [SessionResponse(**row) for row in rows]


@api_router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
)
async def list_messages(
    session_id: int,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> list[MessageResponse]:
    session = await asyncio.to_thread(scope.require_session, session_id)
    rows = await asyncio.to_thread(
        scope.session_store.fetch_session_messages,
        session,
    )
    return [MessageResponse(**row) for row in rows]


@api_router.get(
    "/sessions/{session_id}/turns",
    response_model=list[TurnResponse],
)
async def list_turns(
    session_id: int,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> list[TurnResponse]:
    session = await asyncio.to_thread(scope.require_session, session_id)
    turns = await asyncio.to_thread(
        scope.turn_store.list_turns,
        user_id=session.user_id,
        session_id=session.session_id,
    )
    return [turn_response(turn) for turn in turns]


@api_router.post("/messages", response_model=TurnResponse)
async def create_message(
    payload: MessageRequest,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> TurnResponse:
    session = await asyncio.to_thread(scope.require_session, payload.session_id)
    turn = await asyncio.to_thread(
        scope.turn_store.create_turn,
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
    turn = await asyncio.to_thread(scope.require_turn, turn_id)
    return turn_response(turn)


@api_router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: str,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
    after_seq: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await asyncio.to_thread(scope.require_turn, turn_id)
    cursor = after_seq
    if after_seq == 0 and last_event_id is not None:
        try:
            cursor = max(0, int(last_event_id))
        except ValueError:
            cursor = 0
    return StreamingResponse(
        turn_event_stream(scope.turn_store, turn_id, after_seq=cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@api_router.post("/turns/{turn_id}/cancel", response_model=TurnResponse)
async def cancel_turn(
    turn_id: str,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> TurnResponse:
    turn = await asyncio.to_thread(scope.require_turn, turn_id)
    cancelled = await asyncio.to_thread(scope.turn_store.request_cancel, turn.id)
    return turn_response(cancelled)


@api_router.post("/turns/{turn_id}/retry", response_model=TurnResponse)
async def retry_turn(
    turn_id: str,
    scope: Annotated[OwnerScope, Depends(get_owner_scope)],
) -> TurnResponse:
    turn = await asyncio.to_thread(scope.require_turn, turn_id)
    retried = await asyncio.to_thread(
        scope.turn_store.retry_turn,
        turn_id=turn.id,
        user_id=scope.user_id,
    )
    return turn_response(retried)
