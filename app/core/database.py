"""SQLAlchemy engine, session, and Base. Works with SQLite (local) and
Postgres (Render) transparently."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_url = settings.sqlalchemy_url
# SQLite needs check_same_thread=False for FastAPI's threadpool
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Import models first so they're registered."""
    from app import models  # noqa: F401  (registers all model classes)
    Base.metadata.create_all(bind=engine)
