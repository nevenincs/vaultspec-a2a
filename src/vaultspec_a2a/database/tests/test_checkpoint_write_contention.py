"""A contended checkpoint store delays a write; it never poisons the connection.

Two writers on one SQLite file is an ordinary condition. The application store
has answered it with a bounded retry and a typed refusal since the ``/v1`` verbs
gained one; the checkpoint store had neither, and the saver's own writes made the
condition permanent rather than transient.

Both halves are driven here against a real on-disk store opened by the
production factory, with a real second SQLite connection holding a real
``BEGIN IMMEDIATE``:

* a competing writer that lets go inside the retry budget must not fail the write
  at all - the graph event stream failed a whole run over this;
* contention that outlasts the budget must leave the saver's shared connection
  with no transaction open. A deferred transaction that survives a refusal is
  joined by the saver's next read, which pins a write-ahead-log snapshot nothing
  ever releases: the log can no longer be checkpointed, and every later write on
  that connection is refused instantly without consulting ``busy_timeout``.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint

from ...testing import settings_override
from ..checkpoints import open_checkpointer
from ..session import WriteContentionError, checkpoint_wal

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ..checkpoints import Checkpointer

#: Long enough that an uncontended write never meets it, short enough that the
#: whole retry budget (four attempts plus their growing pauses) finishes well
#: inside a test.
_BUSY_TIMEOUT_MS = 150

#: Held for longer than one attempt's lock wait and well inside the budget, so
#: the write can only succeed by being retried after the writer lets go.
_TRANSIENT_HOLD_SECONDS = 0.6

_RUN_ID = "contended-checkpoint-run"


def _run_config(run_id: str = _RUN_ID) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}


def _competing_row(checkpoint_id: str) -> str:
    return (
        "INSERT OR REPLACE INTO checkpoints "
        "(thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata) "
        f"VALUES ('competitor', '', '{checkpoint_id}', 'json', X'00', X'00')"
    )


@contextmanager
def _competing_writer(store: Path) -> Generator[sqlite3.Connection]:
    """Hold the checkpoint store's write lock from another real connection."""
    holder = sqlite3.connect(store, isolation_level=None, timeout=10.0)
    try:
        holder.execute("PRAGMA busy_timeout=10000")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(_competing_row("held"))
        yield holder
    finally:
        holder.rollback()
        holder.close()


@pytest.mark.asyncio
async def test_a_transient_competing_writer_delays_a_checkpoint_write(
    tmp_path: Path,
) -> None:
    """A writer that lets go inside the budget costs latency, not the run."""
    store = tmp_path / "checkpoints.sqlite"
    with settings_override(
        checkpoint_database_url=f"sqlite+aiosqlite:///{store}",
        sqlite_busy_timeout_ms=_BUSY_TIMEOUT_MS,
    ):
        async with open_checkpointer() as checkpointer:
            with _competing_writer(store) as holder:

                async def release_after_one_attempt() -> None:
                    await asyncio.sleep(_TRANSIENT_HOLD_SECONDS)
                    holder.rollback()

                releasing = asyncio.create_task(release_after_one_attempt())
                started = time.monotonic()
                saved = await checkpointer.aput(
                    _run_config(), empty_checkpoint(), {}, {}
                )
                waited = time.monotonic() - started
                await releasing

            # The write landed, and it landed only after the lock came free:
            # a first attempt that answered inside its own lock wait would mean
            # the competing writer never held it.
            assert waited >= _TRANSIENT_HOLD_SECONDS
            read = await checkpointer.aget_tuple(_run_config())

    assert read is not None
    assert read.checkpoint["id"] == saved.get("configurable", {})["checkpoint_id"]


async def _writes_land_again(checkpointer: Checkpointer) -> None:
    """A write on the now-uncontended store, so a refusal here is the residue."""
    await checkpointer.aput(_run_config(), empty_checkpoint(), {}, {})


@pytest.mark.asyncio
async def test_exhausted_checkpoint_contention_leaves_no_transaction_open(
    tmp_path: Path,
) -> None:
    """The refusal is typed, and the shared connection survives it intact."""
    store = tmp_path / "checkpoints.sqlite"
    with settings_override(
        checkpoint_database_url=f"sqlite+aiosqlite:///{store}",
        sqlite_busy_timeout_ms=_BUSY_TIMEOUT_MS,
    ):
        async with open_checkpointer() as checkpointer:
            await checkpointer.aput(_run_config(), empty_checkpoint(), {}, {})
            with _competing_writer(store) as holder:
                with pytest.raises(WriteContentionError) as refused:
                    await checkpointer.aput(_run_config(), empty_checkpoint(), {}, {})
                holder.commit()

            assert "nothing was applied" in str(refused.value)

            # The graph's next act on the saver is a read. Inside a transaction
            # left open by the refusal it takes a snapshot that nothing commits,
            # which is what pins the log and refuses every later write.
            await checkpointer.aget_tuple(_run_config())

            reader = sqlite3.connect(store, isolation_level=None, timeout=10.0)
            try:
                reader.execute("PRAGMA busy_timeout=10000")
                reader.execute(_competing_row("after-refusal"))
                reclaimed = checkpoint_wal(reader)
            finally:
                reader.close()

            assert not reclaimed.blocked, (
                "the refused write left a snapshot pinning the write-ahead log"
            )
            await _writes_land_again(checkpointer)
