"""SQLModel engine/session setup.

Pitfall 4 (RESEARCH.md): the default sqlite3 connection is
check_same_thread=True, which breaks once a background asyncio task and a
request handler touch the engine from different threads/tasks. Passing
connect_args={"check_same_thread": False} plus a fresh per-operation
Session (never one shared long-lived session) is SQLModel's own documented
FastAPI pattern for this, not a workaround.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """Yield a fresh Session per call — not a shared long-lived one."""
    with Session(engine) as session:
        yield session
