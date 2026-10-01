"""Retention for the checkpoint history of settled runs.

LangGraph writes a full checkpoint at every superstep, and neither saver this
project ships implements ``aprune``, so a settled run kept its entire history -
roughly ten times its transcript - for as long as its thread existed, although
nothing but the latest checkpoint is read once a run is over. Pruning keeps each
namespace's latest checkpoint, the pending writes that belong to it, and (on
PostgreSQL) the channel blobs it references, and removes the rest.

Writing statements against another library's tables is only safe while three
things hold, and each is checked rather than assumed. The saver must not have
grown pruning of its own, which would be authoritative where this is a
stand-in. Its schema must be the one the statements were written for, because
recognising the saver's CLASS says nothing about the version of the tables
behind it. And the thread must not use a delta channel: those keep only a
sentinel in the checkpoint and reconstruct state by walking ancestors, so
dropping the ancestors silently empties the channel with no error to notice.
A saver or a store failing any of these is left untouched rather than guessed
at.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.types import _DeltaSnapshot
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .checkpoint_schema import LANGGRAPH_TABLE_COLUMNS

__all__ = ["prune_settled_checkpoints"]

logger = logging.getLogger(__name__)

# The migration version of the PostgreSQL saver whose tables the statements
# below were written against. Read from ``checkpoint_migrations`` at run time
# and compared: a store the saver has since migrated further is one these
# statements no longer describe.
_POSTGRES_SCHEMA_VERSION = 9

# LangGraph records per-channel delta counters here, and only on threads that
# use a delta channel. It is dropped again the moment every counter resets, so
# a snapshot blob in the checkpoint is the other half of the same signal.
_DELTA_COUNTERS_KEY = "counters_since_delta_snapshot"

# A checkpoint id is time-ordered, and each saver resolves "latest" as the
# greatest id in a namespace, so the same rule decides what survives here.
_SQLITE_PRUNE_WRITES = """
DELETE FROM writes
WHERE thread_id = ?
  AND checkpoint_id <> (
    SELECT MAX(latest.checkpoint_id) FROM checkpoints AS latest
    WHERE latest.thread_id = writes.thread_id
      AND latest.checkpoint_ns = writes.checkpoint_ns
  )
"""
_SQLITE_PRUNE_CHECKPOINTS = """
DELETE FROM checkpoints
WHERE thread_id = ?
  AND checkpoint_id <> (
    SELECT MAX(latest.checkpoint_id) FROM checkpoints AS latest
    WHERE latest.thread_id = checkpoints.thread_id
      AND latest.checkpoint_ns = checkpoints.checkpoint_ns
  )
"""
_POSTGRES_PRUNE_WRITES = """
DELETE FROM checkpoint_writes AS w
WHERE w.thread_id = %s
  AND w.checkpoint_id <> (
    SELECT MAX(latest.checkpoint_id) FROM checkpoints AS latest
    WHERE latest.thread_id = w.thread_id
      AND latest.checkpoint_ns = w.checkpoint_ns
  )
"""
_POSTGRES_PRUNE_CHECKPOINTS = """
DELETE FROM checkpoints AS c
WHERE c.thread_id = %s
  AND c.checkpoint_id <> (
    SELECT MAX(latest.checkpoint_id) FROM checkpoints AS latest
    WHERE latest.thread_id = c.thread_id
      AND latest.checkpoint_ns = c.checkpoint_ns
  )
"""
# Blobs carry no checkpoint id: a blob survives while some remaining checkpoint
# still names its channel at its version.
_POSTGRES_PRUNE_BLOBS = """
DELETE FROM checkpoint_blobs AS b
WHERE b.thread_id = %s
  AND NOT EXISTS (
    SELECT 1 FROM checkpoints AS c
    WHERE c.thread_id = b.thread_id
      AND c.checkpoint_ns = b.checkpoint_ns
      AND c.checkpoint -> 'channel_versions' ->> b.channel = b.version
  )
"""


def scalar(row: Any) -> Any:
    """Return the single column of *row*, whatever row factory produced it."""
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _saver_prunes_itself(checkpointer: object) -> bool:
    """Whether *checkpointer* implements pruning rather than inheriting a refusal."""
    own = getattr(type(checkpointer), "aprune", None)
    return own is not None and own is not BaseCheckpointSaver.aprune


async def _thread_uses_a_delta_channel(checkpointer: Any, thread_id: str) -> bool:
    """Whether *thread_id*'s state depends on ancestors these statements delete.

    A delta channel writes a sentinel and rebuilds its value by walking back to
    the nearest snapshot, so the surviving latest checkpoint is usually not a
    snapshot point and pruning its ancestors would leave the channel
    reconstructing as empty - returning no value rather than raising.
    """
    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    if latest is None:
        return False
    metadata = latest.metadata or {}
    if metadata.get(_DELTA_COUNTERS_KEY):
        return True
    values = latest.checkpoint.get("channel_values") or {}
    return any(isinstance(value, _DeltaSnapshot) for value in values.values())


async def prune_settled_checkpoints(checkpointer: object, thread_id: str) -> bool:
    """Drop every checkpoint of *thread_id* but each namespace's latest.

    Call only for a run that has settled: a live run may still resume from its
    latest checkpoint, which is kept, but nothing older is ever read again.

    Returns:
        ``True`` when the history was pruned, ``False`` when this module will
        not write to the store behind *checkpointer* and left it alone.
    """
    if _saver_prunes_itself(checkpointer):
        # Its own pruning knows its own schema and its own delta channels; the
        # statements here are a stand-in for savers that offer none.
        await cast("Any", checkpointer).aprune([thread_id], strategy="keep_latest")
        return True
    if await _thread_uses_a_delta_channel(checkpointer, thread_id):
        logger.info(
            "Checkpoint retention skipped for thread %s: it uses a delta "
            "channel, whose value is rebuilt from the history a prune removes",
            thread_id,
        )
        return False
    if isinstance(checkpointer, AsyncSqliteSaver):
        return await _prune_sqlite_history(checkpointer, thread_id)
    postgres = _native_postgres_saver(checkpointer)
    if postgres is not None:
        return await _prune_postgres_history(postgres, thread_id)
    logger.debug(
        "Checkpoint retention skipped for thread %s: unsupported saver %s",
        thread_id,
        type(checkpointer).__name__,
    )
    return False


async def _prune_sqlite_history(saver: AsyncSqliteSaver, thread_id: str) -> bool:
    """Prune a SQLite store's history, unless its layout is not the known one."""
    if not await _sqlite_layout_is_the_expected_one(saver):
        return False
    await _prune_sqlite(saver, thread_id)
    return True


async def _prune_postgres_history(saver: Any, thread_id: str) -> bool:
    """Prune a Postgres store's history, unless its schema is not the known one."""
    if not await _postgres_schema_is_the_expected_one(saver):
        return False
    await _prune_postgres(saver, thread_id)
    return True


async def _sqlite_layout_is_the_expected_one(saver: AsyncSqliteSaver) -> bool:
    """Whether the store's tables are the ones the SQLite statements describe.

    SQLite's saver keeps no migration ledger, so the tables are their own
    version: a column added, removed or reordered is a layout these deletes
    were not written for.
    """
    async with saver.lock:
        for table, expected in LANGGRAPH_TABLE_COLUMNS.items():
            async with saver.conn.execute(
                "SELECT name FROM pragma_table_info(?)", (table,)
            ) as cursor:
                found = tuple(str(row[0]) for row in await cursor.fetchall())
            if found != expected:
                logger.warning(
                    "Checkpoint retention skipped: SQLite table %r is %r, not "
                    "the %r these retention statements were written for",
                    table,
                    found,
                    expected,
                )
                return False
    return True


async def _postgres_schema_is_the_expected_one(saver: Any) -> bool:
    """Whether the store is at the saver schema version the statements assume."""
    from psycopg_pool import AsyncConnectionPool

    if isinstance(saver.conn, AsyncConnectionPool):
        async with saver.conn.connection() as connection:
            version = await _postgres_schema_version(connection)
    else:
        async with saver.lock:
            version = await _postgres_schema_version(saver.conn)
    if version == _POSTGRES_SCHEMA_VERSION:
        return True
    logger.warning(
        "Checkpoint retention skipped: the checkpoint store is at saver schema "
        "version %r, not the %r these retention statements were written for",
        version,
        _POSTGRES_SCHEMA_VERSION,
    )
    return False


async def _postgres_schema_version(connection: Any) -> int | None:
    cursor = await connection.execute("SELECT MAX(v) AS v FROM checkpoint_migrations")
    row = await cursor.fetchone()
    if row is None:
        return None
    version = scalar(row)
    return None if version is None else int(version)


async def _prune_sqlite(saver: AsyncSqliteSaver, thread_id: str) -> None:
    async with saver.lock:
        try:
            await saver.conn.execute(_SQLITE_PRUNE_WRITES, (thread_id,))
            await saver.conn.execute(_SQLITE_PRUNE_CHECKPOINTS, (thread_id,))
            await saver.conn.commit()
        except BaseException:
            # The saver's connection is shared, so deletes left open by a failed
            # or cancelled prune would be committed by the saver's next write,
            # half a prune landing on a thread nobody chose to prune then.
            await asyncio.shield(saver.conn.rollback())
            raise


def _native_postgres_saver(checkpointer: object) -> Any | None:
    """Return *checkpointer* when it is the native async PostgreSQL saver.

    Imported lazily: the PostgreSQL driver belongs to the optional server
    profile, and a base install must be able to import this module.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        return None
    return checkpointer if isinstance(checkpointer, AsyncPostgresSaver) else None


async def _prune_postgres(saver: Any, thread_id: str) -> None:
    from psycopg_pool import AsyncConnectionPool

    if isinstance(saver.conn, AsyncConnectionPool):
        async with saver.conn.connection() as connection:
            await _prune_postgres_connection(connection, thread_id)
        return
    async with saver.lock:
        await _prune_postgres_connection(saver.conn, thread_id)


async def _prune_postgres_connection(connection: Any, thread_id: str) -> None:
    async with connection.transaction(), connection.cursor() as cursor:
        await cursor.execute(_POSTGRES_PRUNE_WRITES, (thread_id,))
        await cursor.execute(_POSTGRES_PRUNE_CHECKPOINTS, (thread_id,))
        await cursor.execute(_POSTGRES_PRUNE_BLOBS, (thread_id,))
