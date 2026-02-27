"""Async database session management and engine configuration.

Provides the ``create_async_engine`` factory with SQLite WAL mode (ADR-007),
``async_sessionmaker`` for FastAPI dependency injection, table initialisation,
and a connection to ``langgraph-checkpoint-sqlite``'s ``AsyncSqliteSaver``.

References:
    - ADR-007: SQLite WAL mode, aiosqlite
    - ADR-009: Module hierarchy
"""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


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

# Default database location
DEFAULT_DB_PATH = Path("data/orchestrator.db")


def _set_wal_mode(dbapi_conn: object, _connection_record: object) -> None:
    """Enable WAL journal mode on every new SQLite connection.

    WAL allows concurrent readers while a write is in progress,
    which is critical for the Event Aggregator's high-frequency writes
    (ADR-007 section 5).
    """
    cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(
    db_path: Path | str = DEFAULT_DB_PATH,
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
    global _engine  # noqa: PLW0603

    if _engine is not None:
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
    global _session_factory  # noqa: PLW0603

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
    db_path: Path | str = DEFAULT_DB_PATH,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Initialise the database: create engine, session factory, and all tables.

    Args:
        db_path: Path to the SQLite database file.
        echo: Enable SQL statement logging.

    Returns:
        The initialised ``AsyncEngine``.
    """
    engine = get_engine(db_path, echo=echo)
    get_session_factory(engine)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return engine


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Async generator yielding a database session for FastAPI DI.

    Usage::

        @app.get("/threads")
        async def list_threads(db: AsyncSession = Depends(get_db)): ...
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session


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
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
