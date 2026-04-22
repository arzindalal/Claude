"""
FastAPI dependency providers for database session and ChromaDB embedder.
"""

from __future__ import annotations

from typing import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from ..kb_ingestor.database import get_session
from ..kb_ingestor.embedder import KBEmbedder


def get_db(request: Request) -> Generator[Session, None, None]:
    session = get_session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


def get_embedder(request: Request) -> KBEmbedder:
    return request.app.state.embedder
