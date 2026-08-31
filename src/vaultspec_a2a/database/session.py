"""Async database session management and engine configuration.

Provides backend-selectable ``create_async_engine`` wiring,
``async_sessionmaker`` for FastAPI dependency injection, and schema
initialisation through Alembic.
"""

import logging
import sqlite3
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ..control.config import settings
from .models import Base

logger = logging.getLogger(__name__)


__all__ = [
    "APPLICATION_DATABASE_DECLARATION",
    "ARTIFACT_DECLARATIONS",
    "WalCheckpointResult",
    "application_session_factory",
    "checkpoint_wal",
    "close_db",
    "get_db",
    "get_engine",
    "get_session_factory",
    "init_db",
    "inspect_sqlite_database",
    "verify_wal_mode",
]

# The store this module creates on first connect. Permanence is the right answer
# and is separable from the honest part: the FILE should outlive every process,
# but nothing bounds what accumulates INSIDE it, and no row class here carries an
# age or count limit. The -wal sidecar's ceiling is conditional, which is why
# ``checkpoint_wal`` reports a blocked checkpoint rather than tuning around it.
APPLICATION_DATABASE_DECLARATION = ArtifactDeclaration(
    name="application-database",
    root="<database_path> (plus its -wal and -shm sidecars)",
    owner="database.session",
    disposition=RetentionDisposition.PERMANENT,
    reason=(
        "this is the system of record for runs, threads, artifacts, and the "
        "durable control journal; a run's history is what makes restart "
        "reconciliation and after-the-fact inspection possible, so the store must "
        "outlive every process that opens it"
    ),
    mechanism=(
        "no automatic bound on rows: growth is reclaimed only by operator-timed "
        "verbs (`admin clear --yes` empties application rows, `admin migrate "
        "--fix` truncates the log and VACUUMs pages back to the operating "
        "system). The -wal sidecar settles at SQLite's autocheckpoint ceiling ONLY "
        "while no connection holds an open read transaction; one held transaction "
        "makes it grow linearly with writes and no setting defends against that"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (
    APPLICATION_DATABASE_DECLARATION,
)

# Module-level singletons (set via ``init_db``)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# Two settings are deliberately NOT in the connect posture below. Both were
# proposed as fixes for a database that only ever grows; neither survives
# measurement, and the reasons are recorded here because the absences are the
# decision.
#
# ``wal_autocheckpoint`` is left at SQLite's default of 1000 pages. It is already
# in force - the default is a working ceiling, not an unset knob - and under
# sustained writes with no reader holding a snapshot the log settles near 4 MiB
# and stays there. Restating the default in code would change no behaviour and
# could not be tested apart from it. The ceiling's real limit is that it holds
# only while no connection sits in an open READ TRANSACTION: SQLite cannot
# checkpoint past the oldest live reader snapshot, so a held read transaction
# pins every frame written after it and the log then grows linearly for as long
# as it is held. No autocheckpoint value defends against that - only not holding
# the transaction does - which is why ``checkpoint_wal`` below reports the
# condition instead of trying to tune around it.
#
# ``auto_vacuum`` cannot be set here at all: the ``journal_mode=WAL`` in the
# connect listener writes the database header, and once the header exists
# ``auto_vacuum`` is
# fixed for the life of the file - a later pragma is accepted and silently leaves
# it at NONE. Changing it on an existing install demands a whole-file VACUUM
# rewrite, which is what ``admin migrate --fix`` already offers as an explicit,
# operator-timed act. INCREMENTAL would not earn the trade either: measured
# against a store whose rows had all been deleted, ``incremental_vacuum``
# returned a single 4 KiB page where a full VACUUM returned essentially the whole
# 8 MiB file. Returning space to the operating system therefore stays an
# administrative verb rather than a cost on every commit.


def _set_wal_mode(dbapi_conn: sqlite3.Connection, _connection_record: object) -> None:
    """Enable WAL journal mode on every new SQLite connection.

    WAL allows concurrent readers while a write is in progress,
    which is critical for the Event Aggregator's high-frequency writes.
    """
    cursor = dbapi_conn.cursor()
    # check the return value — PRAGMA journal_mode returns the mode that
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


CheckpointMode = Literal["PASSIVE", "FULL", "RESTART", "TRUNCATE"]

# Interpolating the mode into the statement is only safe because it is checked
# against this set first; SQLite does not accept a bound parameter in a PRAGMA.
_CHECKPOINT_MODES: frozenset[str] = frozenset(
    ("PASSIVE", "FULL", "RESTART", "TRUNCATE")
)


@dataclass(frozen=True, slots=True)
class WalCheckpointResult:
    """The outcome of one ``PRAGMA wal_checkpoint``.

    SQLite reports a checkpoint it could not finish by returning ``busy=1`` with
    the statement still succeeding - no exception, no warning. A caller that
    discards the row cannot tell a log that was truncated from one that was left
    exactly as it found it, which is how a reclaim path comes to report success
    while reclaiming nothing.
    """

    blocked: bool
    log_pages: int
    checkpointed_pages: int

    @property
    def fully_checkpointed(self) -> bool:
        """True when every frame in the log was written back to the database."""
        return not self.blocked and self.log_pages == self.checkpointed_pages


def checkpoint_wal(
    connection: sqlite3.Connection,
    *,
    mode: CheckpointMode = "TRUNCATE",
) -> WalCheckpointResult:
    """Checkpoint the write-ahead log, reporting whether it actually completed.

    ``TRUNCATE`` both writes the log back into the database and resets the file
    to zero length, which is the only mode that returns the log's space to the
    operating system.

    Args:
        connection: An open SQLite connection to the database to checkpoint.
        mode: The checkpoint mode to request.

    Returns:
        The parsed ``(busy, log, checkpointed)`` row.  A database not in WAL mode
        reports ``-1`` page counts, which is a successful no-op rather than a
        failure - there is no log to checkpoint.

    Raises:
        ValueError: If ``mode`` is not a SQLite checkpoint mode.
    """
    if mode not in _CHECKPOINT_MODES:
        msg = f"Unknown SQLite checkpoint mode: {mode!r}"
        raise ValueError(msg)

    row = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
    if row is None:
        # Defensive: every SQLite version in support returns a row here.
        return WalCheckpointResult(blocked=False, log_pages=-1, checkpointed_pages=-1)

    busy, log_pages, checkpointed_pages = (int(value) for value in row[:3])
    result = WalCheckpointResult(
        blocked=bool(busy),
        log_pages=log_pages,
        checkpointed_pages=checkpointed_pages,
    )
    if result.blocked:
        logger.warning(
            "SQLite %s checkpoint was blocked: %d of %d write-ahead log pages "
            "were written back and the log was not reset. A connection is "
            "holding an open read transaction, and the log will keep growing "
            "until it is released.",
            mode,
            result.checkpointed_pages,
            result.log_pages,
        )
    return result


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


def application_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Return the process session factory, or ``None`` if none was initialized.

    The read-only companion to :func:`get_session_factory`, which CREATES an
    engine from ambient settings when none exists. That lazy creation is right
    for a process that owns a database and has simply not opened it yet, and
    wrong for one that owns none at all: it manufactures a connection to a
    settings-derived path and fails at the first query, with nothing naming the
    absent database as the cause.

    Callers that can proceed without durability - an event projection whose
    store is optional - ask this instead, so "this process has no database" stays
    a fact they can read rather than an exception they have to interpret.
    """
    return _session_factory


async def init_db(
    database: Path | str | None = None,
    *,
    echo: bool = False,
    apply_migrations: bool = True,
) -> AsyncEngine:
    """Initialise the database engine, session factory, and schema.

    For file-based databases, schema management is routed through Alembic
    migrations.  For in-memory databases (test use only),
    ``Base.metadata.create_all`` is used directly since Alembic cannot
    target ``:memory:``.

    Args:
        database: Database URL or a SQLite path.
        echo: Enable SQL statement logging.
        apply_migrations: When ``False``, the engine and session factory are
            created but no schema mutation is performed. The desktop product
            profile uses this to keep ordinary boot non-mutating; the caller is
            responsible for validating schema compatibility separately. In-memory
            databases always create their schema, since they are ephemeral test
            stores with no external migration authority.

    Returns:
        The initialised ``AsyncEngine``.
    """
    global _session_factory

    url = _resolve_database_url(database)
    engine = get_engine(url, echo=echo)
    # Seat the APPLICATION factory, not merely a factory for this engine.
    # ``get_session_factory`` deliberately leaves the singleton alone when handed
    # an explicit engine - an explicit engine means "one bound to this", not
    # "adopt this process-wide" - so passing one here built a factory and left
    # the process still reporting no database. This IS the initialisation entry
    # point, so establishing that fact is exactly its job.
    _session_factory = get_session_factory(engine)

    if url == "sqlite+aiosqlite:///:memory:":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    elif apply_migrations:
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

    The ``async with factory() as session`` context manager already
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
