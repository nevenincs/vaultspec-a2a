"""Async database session management and engine configuration.

Provides backend-selectable ``create_async_engine`` wiring,
``async_sessionmaker`` for FastAPI dependency injection, and schema
initialisation through Alembic.

References:
    - ADR-007: SQLite WAL mode, aiosqlite
    - ADR-009: Module hierarchy
"""

import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import settings
from .models import Base

logger = logging.getLogger(__name__)


__all__ = [
    "close_db",
    "get_db",
    "get_engine",
    "get_session_factory",
    "init_db",
    "inspect_sqlite_database",
    "verify_wal_mode",
]

# Module-level singletons (set via ``init_db``)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _set_wal_mode(dbapi_conn: object, _connection_record: object) -> None:
    """Enable WAL journal mode on every new SQLite connection.

    WAL allows concurrent readers while a write is in progress,
    which is critical for the Event Aggregator's high-frequency writes
    (ADR-007 section 5).
    """
    cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
    # H18: check the return value — PRAGMA journal_mode returns the mode that
    # was actually set (or the current mode on read-only filesystems).
    cursor.execute("PRAGMA journal_mode=WAL")
    row = cursor.fetchone()
    actual_mode = row[0] if row else None
    if actual_mode != "wal":
        logger.warning(
            "Failed to enable WAL journal mode; actual mode: %r. "
            "SQLite may be on a network or read-only filesystem.",
            actual_mode,
        )
    cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _resolve_database_url(database: Path | str | None) -> str:
    """Resolve a database path or URL into a SQLAlchemy async URL."""
    if database is None:
        return settings.database_url

    raw = str(database)
    if "://" in raw:
        return raw
    if raw == ":memory:":
        return "sqlite+aiosqlite:///:memory:"

    resolved = Path(raw).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{resolved}"


def get_engine(
    database: Path | str | None = None,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Create or return the async SQLAlchemy engine.

    Args:
        database: Database URL or a SQLite path.
        echo: Enable SQL statement logging.

    Returns:
        The ``AsyncEngine`` instance.
    """
    url = _resolve_database_url(database)
    global _engine
    if _engine is not None:
        existing_url = str(_engine.url)
        if existing_url != url:
            logger.warning(
                "get_engine() called with URL %r but the engine singleton was "
                "already created with %r. Returning the existing engine.",
                url,
                existing_url,
            )
        return _engine

    engine_kwargs: dict[str, object] = {"echo": echo}
    if url.startswith("postgresql"):
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_pool_max_overflow

    _engine = create_async_engine(url, **engine_kwargs)

    if url.startswith("sqlite"):
        event.listen(_engine.sync_engine, "connect", _set_wal_mode)

    return _engine


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Create or return the async session factory.

    Args:
        engine: Optional engine override. Uses the module singleton if None.

    Returns:
        The ``async_sessionmaker`` instance.
    """
    global _session_factory
    if _session_factory is not None and engine is None:
        return _session_factory

    target_engine = engine or get_engine()
    factory = async_sessionmaker(
        target_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    if engine is None:
        _session_factory = factory

    return factory


async def init_db(
    database: Path | str | None = None,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Initialise the database engine, session factory, and schema.

    For file-based databases, schema management is routed through Alembic
    migrations (ADR-029).  For in-memory databases (test use only),
    ``Base.metadata.create_all`` is used directly since Alembic cannot
    target ``:memory:``.

    Args:
        database: Database URL or a SQLite path.
        echo: Enable SQL statement logging.

    Returns:
        The initialised ``AsyncEngine``.
    """
    url = _resolve_database_url(database)
    engine = get_engine(url, echo=echo)
    get_session_factory(engine)

    if url == "sqlite+aiosqlite:///:memory:":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        from .migrate import run_migrations

        await run_migrations(url)

    return engine


async def get_db(
    request: Request,
) -> AsyncGenerator[AsyncSession]:
    """Async generator yielding a database session for FastAPI DI.

    Usage::

        @app.get("/threads")
        async def list_threads(db: AsyncSession = Depends(get_db)): ...

    DB-M3: The ``async with factory() as session`` context manager already
    handles rollback on exception and close on exit.  We wrap in try/finally
    to ensure ``session.close()`` is called even if the generator is abandoned
    mid-stream (e.g. client disconnect before the generator resumes).
    """
    factory = (
        getattr(request.app.state, "db_session_factory", None) or get_session_factory()
    )
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def verify_wal_mode(engine: AsyncEngine) -> str:
    """Verify that WAL mode is active on the given engine.

    Returns:
        The current journal mode string (should be ``'wal'``).
    """
    if engine.dialect.name != "sqlite":
        msg = "verify_wal_mode() is only valid for SQLite engines."
        raise ValueError(msg)
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA journal_mode"))
        row = result.scalar_one()
        return str(row)


def inspect_sqlite_database(path: Path) -> dict[str, object]:
    """Inspect a SQLite file for fallback-mode diagnostics."""
    diagnostics: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "journal_mode": None,
        "wal_enabled": False,
    }
    if not path.exists():
        diagnostics["detail"] = "sqlite file missing"
        return diagnostics

    import sqlite3

    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        diagnostics["detail"] = str(exc)
        return diagnostics

    journal_mode = str(row[0]) if row else ""
    diagnostics["journal_mode"] = journal_mode
    diagnostics["wal_enabled"] = journal_mode.lower() == "wal"
    if not diagnostics["wal_enabled"]:
        diagnostics["detail"] = (
            "WAL unavailable; SQLite may be on a read-only or unsupported filesystem."
        )
    return diagnostics


async def close_db() -> None:
    """Dispose the engine and reset module singletons."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
