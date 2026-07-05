from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import Request

from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore


async def get_turn_store(request: Request) -> PostgresTurnStore:
    return cast(PostgresTurnStore, request.app.state.turn_store)


async def get_session_store(request: Request) -> PostgresSessionStore:
    return cast(PostgresSessionStore, request.app.state.session_store)


async def get_static_dir(request: Request) -> Path:
    return cast(Path, request.app.state.static_dir)
