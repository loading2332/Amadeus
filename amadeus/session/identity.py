from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

_SESSION_KEY_RE = re.compile(r"^user:(?P<user_id>\d+):session:(?P<session_id>\d+)$")


@dataclass(frozen=True)
class SessionRef:
    user_id: int
    session_id: int

    @property
    def session_key(self) -> str:
        return build_session_key(self.user_id, self.session_id)

    def __str__(self) -> str:
        return self.session_key


SessionRefLike: TypeAlias = SessionRef | str


def parse_session_key(key: str) -> tuple[int, int] | None:
    match = _SESSION_KEY_RE.match(str(key))
    if match is None:
        return None
    return int(match.group("user_id")), int(match.group("session_id"))


def parse_session_ref(value: SessionRefLike) -> SessionRef | None:
    if isinstance(value, SessionRef):
        return value
    parsed = parse_session_key(value)
    if parsed is None:
        return None
    return SessionRef(*parsed)


def require_session_key(key: str) -> tuple[int, int]:
    parsed = parse_session_key(key)
    if parsed is None:
        raise ValueError(
            f"PostgreSQL session key must use user/session shape: {key}"
        )
    return parsed


def require_session_ref(value: SessionRefLike) -> SessionRef:
    session = parse_session_ref(value)
    if session is None:
        raise ValueError(
            f"PostgreSQL session key must use user/session shape: {value}"
        )
    return session


def build_session_key(user_id: int, session_id: int) -> str:
    return f"user:{int(user_id)}:session:{int(session_id)}"


def session_key_for(value: SessionRefLike) -> str:
    session = parse_session_ref(value)
    return session.session_key if session is not None else str(value)


def build_message_id(user_id: int, session_id: int, seq: int) -> str:
    return f"session:{int(user_id)}:{int(session_id)}:{int(seq)}"
