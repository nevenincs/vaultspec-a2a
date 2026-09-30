"""Retention for the checkpoint history of settled runs.

LangGraph writes a full checkpoint at every superstep, and neither saver this
project ships implements ``aprune``, so a settled run kept its entire history -
roughly ten times its transcript - for as long as its thread existed, although
nothing but the latest checkpoint is read once a run is over. Pruning keeps each
namespace's latest checkpoint, the pending writes that belong to it, and (on
PostgreSQL) the channel blobs it references, and removes the rest.

The statements are written against each saver's own tables because the saver
interface offers no pruning of its own. A saver this module does not recognise
is left untouched rather than guessed at.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

__all__ = ["prune_settled_checkpoints"]

logger = logging.getLogger(__name__)

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


async def prune_settled_checkpoints(checkpointer: object, thread_id: str) -> bool:
    """Drop every checkpoint of *thread_id* but each namespace's latest.

    Call only for a run that has settled: a live run may still resume from its
    latest checkpoint, which is kept, but nothing older is ever read again.

    Returns:
        ``True`` when the saver was pruned, ``False`` when this module does not
        recognise the saver and left it alone.
    """
    if isinstance(checkpointer, AsyncSqliteSaver):
        await _prune_sqlite(checkpointer, thread_id)
        return True
    postgres = _native_postgres_saver(checkpointer)
    if postgres is not None:
        await _prune_postgres(postgres, thread_id)
        return True
    logger.debug(
        "Checkpoint retention skipped for thread %s: unsupported saver %s",
        thread_id,
        type(checkpointer).__name__,
    )
    return False


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
