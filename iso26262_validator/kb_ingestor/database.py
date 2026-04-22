"""SQLite engine and session factory."""

from pathlib import Path
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

# Module-level factory cache: one factory per engine (keyed by DB path).
_factories: dict[str, sessionmaker] = {}


def get_engine(db_path: str = "data/kb.sqlite") -> Engine:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine: Engine) -> Session:
    url = str(engine.url)
    if url not in _factories:
        _factories[url] = sessionmaker(engine)
    return _factories[url]()
