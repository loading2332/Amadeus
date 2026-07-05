from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from amadeus.app.bootstrap import default_workspace_root, load_runtime_config
from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore
from amadeus.web.routes import api_router
from amadeus.web.static_routes import static_router


def create_app(
    *,
    store: PostgresTurnStore | None = None,
    session_store: PostgresSessionStore | None = None,
    workspace_root: str | Path | None = None,
    env_path: str | Path = ".env",
    static_dir: str | Path | None = None,
) -> FastAPI:
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else default_workspace_root()
    )
    if store is None:
        config = load_runtime_config(env_path=env_path, workspace_root=root)
        turn_store = PostgresTurnStore(config.postgres_dsn)
        resolved_session_store = session_store or PostgresSessionStore(config.postgres_dsn)
    else:
        if session_store is None:
            raise ValueError("session_store is required when injecting a turn store")
        turn_store = store
        resolved_session_store = session_store
    resolved_static_dir = (
        Path(static_dir)
        if static_dir is not None
        else Path(__file__).with_name("static")
    )

    app = FastAPI(title="Amadeus Web Chat")
    app.state.turn_store = turn_store
    app.state.session_store = resolved_session_store
    app.state.static_dir = resolved_static_dir

    if resolved_static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=resolved_static_dir),
            name="static",
        )

    app.include_router(static_router)
    app.include_router(api_router, prefix="/api")

    return app
