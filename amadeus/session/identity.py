from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionRef:
    user_id: int
    session_id: int

    @property
    def identity(self) -> tuple[int, int]:
        return int(self.user_id), int(self.session_id)


def build_message_id(user_id: int, session_id: int, seq: int) -> str:
    return f"session:{int(user_id)}:{int(session_id)}:{int(seq)}"
