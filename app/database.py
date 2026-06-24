"""SQLAlchemy engine, session factory, and dependency for FastAPI routes."""
from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger("summer.db")

# Default to a local file inside ./data. The Docker compose file pins this to
# a fixed path inside the container, and bind-mounts ./data from the host so
# the SQLite file survives container restarts.
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
    """Create all tables, then apply any pending light migrations."""
    # Ensure the parent directory exists (relevant for the SQLite default path)
    if DATABASE_URL.startswith("sqlite"):
        db_path = DATABASE_URL.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Import models so they register with the metadata before create_all
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_light_migrations(engine)


def _run_light_migrations(engine) -> None:
    """Apply idempotent schema fixes for live databases.

    `Base.metadata.create_all()` only creates missing tables — it never
    adds columns to an existing table. Once the schema evolves (e.g. the
    pending-approval workflow added `status` and `denial_reason` to
    `chore_completions`), existing DBs would be left out of sync with
    the model. Each statement here is wrapped to be a no-op on re-run.
    """
    statements: list[str] = [
        # pending-approval workflow for chore completions
        "ALTER TABLE chore_completions ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'approved'",
        "ALTER TABLE chore_completions ADD COLUMN denial_reason VARCHAR(256) NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS ix_chore_completions_status ON chore_completions (status)",
        # pending-approval workflow for reward redemptions (mirrors the
        # chore_completions changes; see app/models.py docstring)
        "ALTER TABLE reward_redemptions ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'approved'",
        "ALTER TABLE reward_redemptions ADD COLUMN denial_reason VARCHAR(256) NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS ix_reward_redemptions_status ON reward_redemptions (status)",
        # per-kid PIN column (v0.1.8)
        "ALTER TABLE kids ADD COLUMN pin VARCHAR(12)",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                log.info("migration applied: %s", stmt.split("\n")[0])
            except Exception as e:  # noqa: BLE001 - SQLite is chatty on re-run
                log.info("migration no-op: %s (%s)", stmt.split("\n")[0], e)
