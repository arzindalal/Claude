"""
FastAPI application factory for the ISO 26262 Validation Tool.

Environment variables
---------------------
  KB_DB     — path to SQLite database  (default: data/kb.sqlite)
  KB_CHROMA — path to ChromaDB storage (default: data/chroma)

Run:
  uvicorn iso26262_validator.api.app:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from ..kb_ingestor.database import get_engine
from ..kb_ingestor.embedder import KBEmbedder
from ..kb_ingestor.models import Base
from .routers import export, rest, ui

_DB_PATH = os.environ.get("KB_DB", "data/kb.sqlite")
_CHROMA_PATH = os.environ.get("KB_CHROMA", "data/chroma")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine(_DB_PATH)
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.embedder = KBEmbedder(chroma_path=_CHROMA_PATH)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="ISO 26262 Validation Tool",
        version="0.3.0",
        lifespan=lifespan,
    )
    application.include_router(ui.router)
    application.include_router(rest.router, prefix="/api", tags=["REST"])
    application.include_router(export.router, prefix="/api", tags=["Export"])
    return application


app = create_app()
