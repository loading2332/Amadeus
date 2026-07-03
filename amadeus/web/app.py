from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from amadeus.app.bootstrap import default_workspace_root
from amadeus.turns import TurnStore
from amadeus.web.routes import api_router
from amadeus.web.static_routes import static_router


def create_app(
    *,
    store: TurnStore | None = None,
    workspace_root: str | Path | None = None,
    static_dir: str | Path | None = None,
) -> FastAPI:
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else default_workspace_root()
    )
    turn_store = store or TurnStore(root / "turns.db")
    resolved_static_dir = (
        Path(static_dir)
        if static_dir is not None
        else Path(__file__).with_name("static")
    )

    app = FastAPI(title="Amadeus Web Chat")
    app.state.turn_store = turn_store
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
