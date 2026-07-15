"""SQLModel engine/session setup.

Pitfall 4 (RESEARCH.md): the default sqlite3 connection is
check_same_thread=True, which breaks once a background asyncio task and a
request handler touch the engine from different threads/tasks. Passing
connect_args={"check_same_thread": False} plus a fresh per-operation
Session (never one shared long-lived session) is SQLModel's own documented
FastAPI pattern for this, not a workaround.

Pitfall 5: Phase 3 adds materially more concurrent write traffic (per-row
regen + batch generation + SSE progress reads) than Phase 1/2 had, enough
to trip SQLite's default rollback-journal locking. `_set_sqlite_pragma`
enables WAL (readers don't block on a writer) + a busy_timeout on every new
connection.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# SQLModel's create_all() never ALTERs an existing table — a real
# projects.db from an earlier phase already exists without these columns.
# Additive-only, idempotent column migrator, not a schema-migration
# framework. ponytail: this is the ceiling; upgrade to Alembic if the
# project ever needs down-migrations or column renames/drops.
_NEW_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "segment": [
        ("generation_status", "TEXT DEFAULT 'pending'"),
        ("generation_error", "TEXT"),
        ("audio_path", "TEXT"),
        ("cache_key", "TEXT"),
        ("generation_version", "INTEGER DEFAULT 0"),
    ],
    "project": [
        ("created_at", "TEXT"),
        ("output_path", "TEXT"),
        ("tts_model", "TEXT DEFAULT '1.7b'"),
        ("output_format", "TEXT DEFAULT 'mp3'"),
        ("output_filename", "TEXT"),
    ],
}


def _ensure_columns() -> None:
    with engine.connect() as connection:
        for table, columns in _NEW_COLUMNS.items():
            existing = {
                row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            for name, sql_type in columns:
                if name not in existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"
                    )
        connection.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_columns()


def get_session() -> Iterator[Session]:
    """Yield a fresh Session per call — not a shared long-lived one."""
    with Session(engine) as session:
        yield session
