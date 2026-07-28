from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TURN_PENDING = "pending"
TURN_PROCESSING = "processing"
TURN_FINALIZING = "finalizing"
TURN_DONE = "done"
TURN_FAILED = "failed"
TURN_CANCELLED = "cancelled"
TERMINAL_TURN_STATUSES = {TURN_DONE, TURN_FAILED, TURN_CANCELLED}
ACTIVE_TURN_STATUSES = {TURN_PENDING, TURN_PROCESSING, TURN_FINALIZING}


class ActiveTurnExists(RuntimeError):
    """The owner/session already has a pending or processing turn."""


class InvalidTurnTransition(RuntimeError):
    """A turn mutation no longer matches the active status or lease."""


@dataclass(frozen=True)
class TurnError:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class TurnEvent:
    turn_id: str
    seq: int
    type: str
    data: dict[str, Any]
    occurred_at: str


@dataclass(frozen=True)
class TurnExecutionResult:
    answer: str
    user_message_id: str
    assistant_message_id: str
    explicit_memory_ids: tuple[str, ...] = ()
    enqueue_post_response_memory: bool = False


@dataclass(frozen=True)
class Turn:
    id: str
    user_id: int
    session_id: int
    content: str
    status: str
    answer: str | None
    error: str | None
    error_code: str | None
    error_message: str | None
    error_retryable: bool | None
    metadata: dict[str, Any]
    attempts: int
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    partial_answer: str = ""
    stream_version: int = 0
    next_event_seq: int = 0
    cancel_requested_at: str | None = None
    heartbeat_at: str | None = None
    lease_id: str | None = None
    retry_of_turn_id: str | None = None
