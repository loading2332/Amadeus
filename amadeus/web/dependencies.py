from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import Request

from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore
from amadeus.web.owner import OwnerScope


async def get_owner_scope(request: Request) -> OwnerScope:
    return OwnerScope(
        user_id=int(request.app.state.owner_user_id),
        session_store=cast(PostgresSessionStore, request.app.state.session_store),
        turn_store=cast(PostgresTurnStore, request.app.state.turn_store),
    )


async def get_static_dir(request: Request) -> Path:
    return cast(Path, request.app.state.static_dir)
