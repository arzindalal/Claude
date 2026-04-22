"""SQLite engine and session factory."""

from pathlib import Path
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base


def get_engine(db_path: str = "data/kb.sqlite") -> Engine:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine: Engine) -> Session:
    SessionFactory = sessionmaker(bind=engine)
    return SessionFactory()
