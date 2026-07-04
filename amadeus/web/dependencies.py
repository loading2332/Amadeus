from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import Request

from amadeus.turns import TurnStore


async def get_turn_store(request: Request) -> TurnStore:
    return cast(TurnStore, request.app.state.turn_store)


async def get_session_store(request: Request) -> Any:
    return request.app.state.session_store


async def get_static_dir(request: Request) -> Path:
    return cast(Path, request.app.state.static_dir)
