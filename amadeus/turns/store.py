from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TURN_PENDING = "pending"
TURN_PROCESSING = "processing"
TURN_DONE = "done"
TURN_FAILED = "failed"
TERMINAL_TURN_STATUSES = {TURN_DONE, TURN_FAILED}


@dataclass(frozen=True)
class Turn:
    id: str
    session_key: str
    content: str
    status: str
    answer: str | None
    error: str | None
    metadata: dict[str, Any]
    attempts: int
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    user_id: int | None = None
    session_id: int | None = None
