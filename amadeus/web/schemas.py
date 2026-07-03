from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from amadeus.turns import Turn


class HealthResponse(BaseModel):
    status: str = "ok"


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)
    session_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnResponse(BaseModel):
    turn_id: str
    session_key: str
    status: str
    answer: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


def turn_response(turn: Turn) -> TurnResponse:
    return TurnResponse(
        turn_id=turn.id,
        session_key=turn.session_key,
        status=turn.status,
        answer=turn.answer,
        error=turn.error,
        metadata=turn.metadata,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
        started_at=turn.started_at,
        finished_at=turn.finished_at,
    )
