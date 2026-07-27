from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import HTTPException, Request

from amadeus.auth import AuthService, CurrentUser
from amadeus.auth.service import AuthenticationError
from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore
from amadeus.web.auth_routes import ACCESS_COOKIE
from amadeus.web.owner import OwnerScope


async def get_owner_scope(request: Request) -> OwnerScope:
    current_user = await get_current_user(request)
    return OwnerScope(
        user_id=current_user.user_id,
        session_store=cast(PostgresSessionStore, request.app.state.session_store),
        turn_store=cast(PostgresTurnStore, request.app.state.turn_store),
    )


async def get_current_user(request: Request) -> CurrentUser:
    test_owner_user_id = getattr(request.app.state, "test_owner_user_id", None)
    if test_owner_user_id is not None:
        return CurrentUser(user_id=int(test_owner_user_id))
    token = request.cookies.get(ACCESS_COOKIE)
    service = cast(AuthService, request.app.state.auth_service)
    try:
        return service.verify_access(token or "")
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail="需要登录") from error


async def get_static_dir(request: Request) -> Path:
    return cast(Path, request.app.state.static_dir)
