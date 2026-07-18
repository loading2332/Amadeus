from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from amadeus.session.identity import SessionRef
from amadeus.session.postgres import PostgresSessionStore
from amadeus.turns.postgres import PostgresTurnStore
from amadeus.turns.store import Turn


class OwnerResourceNotFound(LookupError):
    """The requested Web resource is missing or outside the owner scope."""


@dataclass(frozen=True)
class OwnerScope:
    user_id: int
    session_store: PostgresSessionStore
    turn_store: PostgresTurnStore

    def require_session(self, session_id: int) -> SessionRef:
        session = SessionRef(self.user_id, int(session_id))
        if self.session_store.get_session_meta(session) is None:
            raise OwnerResourceNotFound()
        return session

    def require_turn(self, turn_id: str) -> Turn:
        turn = self.turn_store.get_turn(turn_id)
        if turn is None or turn.user_id != self.user_id:
            raise OwnerResourceNotFound()
        return turn


_RESERVED_WEB_METADATA = frozenset(
    {"channel", "user_id", "session_id", "turn_id"}
)


def web_turn_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe = {
        key: value
        for key, value in metadata.items()
        if key not in _RESERVED_WEB_METADATA
    }
    safe["channel"] = "web"
    return safe
