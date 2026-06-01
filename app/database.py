"""SQLAlchemy engine, session factory, and dependency for FastAPI routes."""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Default to a local file inside ./data. The Docker compose file overrides this
# to a path on the named volume so data survives container restarts.
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "summer.db"
_DEFAULT_DB_URL = f"sqlite:///{_DEFAULT_DB_PATH}"

DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)

# SQLite needs check_same_thread=False when used across the async event loop
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    # Ensure the parent directory exists (relevant for the SQLite default path)
    if DATABASE_URL.startswith("sqlite"):
        db_path = DATABASE_URL.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Import models so they register with the metadata before create_all
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
