from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from amadeus.app.bootstrap import default_workspace_root, load_runtime_config
from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore
from amadeus.turns.store import ActiveTurnExists, InvalidTurnTransition
from amadeus.web.owner import OwnerResourceNotFound
from amadeus.web.routes import api_router
from amadeus.web.static_routes import static_router


def create_app(
    *,
    store: PostgresTurnStore | None = None,
    session_store: PostgresSessionStore | None = None,
    workspace_root: str | Path | None = None,
    env_path: str | Path = ".env",
    static_dir: str | Path | None = None,
    owner_user_id: int | None = None,
) -> FastAPI:
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else default_workspace_root()
    )
    if store is None:
        if owner_user_id is not None:
            raise ValueError(
                "owner_user_id is only accepted with injected Web stores"
            )
        config = load_runtime_config(env_path=env_path, workspace_root=root)
        turn_store = PostgresTurnStore(config.postgres_dsn)
        resolved_session_store = session_store or PostgresSessionStore(config.postgres_dsn)
        resolved_owner_user_id = config.owner_user_id
    else:
        if session_store is None:
            raise ValueError("session_store is required when injecting a turn store")
        if owner_user_id is None or int(owner_user_id) <= 0:
            raise ValueError(
                "owner_user_id must be a positive integer when injecting Web stores"
            )
        turn_store = store
        resolved_session_store = session_store
        resolved_owner_user_id = int(owner_user_id)
    resolved_static_dir = (
        Path(static_dir)
        if static_dir is not None
        else Path(__file__).with_name("static")
    )

    app = FastAPI(title="Amadeus Web Chat")
    app.state.turn_store = turn_store
    app.state.session_store = resolved_session_store
    app.state.owner_user_id = resolved_owner_user_id
    app.state.static_dir = resolved_static_dir

    @app.exception_handler(OwnerResourceNotFound)
    async def owner_resource_not_found(
        request: Request,
        error: OwnerResourceNotFound,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(status_code=404, content={"detail": "Resource not found"})

    @app.exception_handler(ActiveTurnExists)
    async def active_turn_exists(
        request: Request,
        error: ActiveTurnExists,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=409,
            content={
                "code": "active_turn_exists",
                "detail": "该会话已有正在处理的请求",
            },
        )

    @app.exception_handler(InvalidTurnTransition)
    async def invalid_turn_transition(
        request: Request,
        error: InvalidTurnTransition,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=409,
            content={
                "code": "invalid_turn_transition",
                "detail": "当前请求状态不允许此操作",
            },
        )

    if resolved_static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=resolved_static_dir),
            name="static",
        )

    app.include_router(static_router)
    app.include_router(api_router, prefix="/api")

    return app
