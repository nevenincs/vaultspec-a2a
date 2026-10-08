"""Retention for the checkpoint history of settled runs.

LangGraph writes a full checkpoint at every superstep, and the saver this
project ships does not implement ``aprune``, so a settled run kept its entire
history - roughly ten times its transcript - for as long as its thread existed,
although nothing but the latest checkpoint is read once a run is over. Pruning
keeps each namespace's latest checkpoint and the pending writes that belong to
it, and removes the rest.

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
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .checkpoint_schema import LANGGRAPH_TABLE_COLUMNS

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["prune_settled_checkpoints"]

logger = logging.getLogger(__name__)

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


def _saver_prunes_itself(checkpointer: object) -> bool:
    """Whether *checkpointer* implements pruning rather than inheriting a refusal."""
    own = getattr(type(checkpointer), "aprune", None)
    return own is not None and own is not cast("object", BaseCheckpointSaver.aprune)


async def _thread_uses_a_delta_channel(checkpointer: Any, thread_id: str) -> bool:
    """Whether *thread_id*'s state depends on ancestors these statements delete.

    A delta channel writes a sentinel and rebuilds its value by walking back to
    the nearest snapshot, so a latest checkpoint that is not a snapshot point
    would reconstruct the channel as empty once its ancestors are gone -
    returning no value rather than raising.

    LangGraph records exactly that dependency: the latest checkpoint's
    metadata counts the writes each delta channel has taken since its last
    snapshot, and drops the count only when every delta channel snapshotted
    in that checkpoint. A snapshot holds the channel's whole accumulated value,
    so a head with no count needs nothing older and is pruned like any other.

    A read that does not answer raises, so no history is pruned on a guess.
    """
    # Deferred: the checkpoint module imports this one to prune through it.
    from .checkpoints import read_latest_checkpoint

    latest = (await read_latest_checkpoint(checkpointer, thread_id)).tuple_or_raise()
    if latest is None:
        return False
    metadata: Mapping[str, object] = latest.metadata or {}
    return bool(metadata.get(_DELTA_COUNTERS_KEY))


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
