"""Async database session management and engine configuration.

Provides the ``create_async_engine`` factory with SQLite WAL mode (ADR-007),
``async_sessionmaker`` for FastAPI dependency injection, table initialisation,
and a connection to ``langgraph-checkpoint-sqlite``'s ``AsyncSqliteSaver``.

References:
    - ADR-007: SQLite WAL mode, aiosqlite
    - ADR-009: Module hierarchy
"""

import logging

from collections.abc import AsyncGenerator
from pathlib import Path

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
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(
    db_path: Path | str | None = None,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Create or return the async SQLAlchemy engine.

    Args:
        db_path: Path to the SQLite database file.
                 Use ``:memory:`` for in-memory databases.
        echo: Enable SQL statement logging.

    Returns:
        The ``AsyncEngine`` instance.
    """
    if db_path is None:
        db_path = settings.database_path
    global _engine
    if _engine is not None:
        # H19: warn if called with a different path than the existing singleton,
        # since the caller will silently get the original engine back.
        requested = str(db_path)
        existing_url = str(_engine.url)
        if requested != ":memory:":
            # Compare resolved absolute paths to avoid false positives from
            # differing relative-path representations of the same file.
            resolved_requested = Path(requested).resolve()
            resolved_default = settings.database_path.resolve()
            if resolved_requested != resolved_default:
                # Extract the path component from the existing engine URL for
                # a proper resolved comparison (not a substring check).
                existing_path_str = (
                    existing_url.split("///", 1)[1] if "///" in existing_url else ""
                )
                existing_resolved = (
                    Path(existing_path_str).resolve() if existing_path_str else None
                )
                if existing_resolved != resolved_requested:
                    logger.warning(
                        "get_engine() called with path %r but the engine singleton "
                        "was already created with a different path (%r). "
                        "Returning existing engine.",
                        requested,
                        existing_url,
                    )
        return _engine

    db_path_str = str(db_path)
    if db_path_str == ":memory:":
        url = "sqlite+aiosqlite:///:memory:"
    else:
        resolved = Path(db_path_str).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{resolved}"

    _engine = create_async_engine(url, echo=echo)

    # Attach WAL pragma to the synchronous engine underneath
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
    db_path: Path | str | None = None,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Initialise the database engine, session factory, and schema.

    For file-based databases, schema management is routed through Alembic
    migrations (ADR-029).  For in-memory databases (test use only),
    ``Base.metadata.create_all`` is used directly since Alembic cannot
    target ``:memory:``.

    Args:
        db_path: Path to the SQLite database file.
        echo: Enable SQL statement logging.

    Returns:
        The initialised ``AsyncEngine``.
    """
    if db_path is None:
        db_path = settings.database_path
    engine = get_engine(db_path, echo=echo)
    get_session_factory(engine)

    str_path = str(db_path)
    if str_path in (":memory:", ""):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        from .migrate import run_migrations  # noqa: PLC0415

        url = f"sqlite+aiosqlite:///{str_path}"
        await run_migrations(url)

    return engine


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Async generator yielding a database session for FastAPI DI.

    Usage::

        @app.get("/threads")
        async def list_threads(db: AsyncSession = Depends(get_db)): ...

    DB-M3: The ``async with factory() as session`` context manager already
    handles rollback on exception and close on exit.  We wrap in try/finally
    to ensure ``session.close()`` is called even if the generator is abandoned
    mid-stream (e.g. client disconnect before the generator resumes).
    """
    factory = get_session_factory()
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
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA journal_mode"))
        row = result.scalar_one()
        return str(row)


async def close_db() -> None:
    """Dispose the engine and reset module singletons."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
