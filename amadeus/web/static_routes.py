from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from amadeus.web.dependencies import get_static_dir

static_router = APIRouter(include_in_schema=False)


@static_router.get("/")
async def index(static_dir: Annotated[Path, Depends(get_static_dir)]) -> FileResponse:
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Web page is not available")
    return FileResponse(index_path)
