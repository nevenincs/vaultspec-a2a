"""The real write-lock holder every store-contention test contends against.

SQLite admits one writer at a time, and the only honest way to prove how this
code answers a busy store is to make the store genuinely busy: a second real
connection to the same file holding a real ``BEGIN IMMEDIATE`` for as long as the
test needs. Nothing is simulated, so what the production retry policy, the typed
refusal and the degraded read meet here is the driver's own refusal.

One holder, because the three suites that needed one wrote the same connect,
``PRAGMA busy_timeout``, ``BEGIN IMMEDIATE``, write, rollback, close sequence and
each got a slightly different variant of it - a drift that matters because the
exact shape of the hold is what decides whether the writer under test meets the
lock at all.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

__all__ = ["HOLDER_LOCK_WAIT_MS", "held_write_lock"]

HOLDER_LOCK_WAIT_MS = 10_000
"""The holder's own lock wait.

Generous on purpose and never the value under test: the holder has to WIN the
lock for the test to mean anything, so it waits far longer for it than the
narrowed wait the code under test is given.
"""


@contextmanager
def held_write_lock(
    store: Path,
    *,
    statement: str | None = None,
    parameters: Sequence[object] = (),
    lock_wait_ms: int = HOLDER_LOCK_WAIT_MS,
) -> Generator[sqlite3.Connection]:
    """Hold *store*'s SQLite write lock from another real connection.

    The yielded connection is the hold itself, so a test that needs the lock to
    come free DURING its block releases it there (``rollback()`` to abandon the
    holder's write, ``commit()`` to keep it); on leaving the block the hold is
    rolled back and the connection closed either way, which is a no-op once the
    test already settled it.

    *statement* is an optional write executed inside the transaction, with
    *parameters* bound. ``BEGIN IMMEDIATE`` already takes the write lock, so the
    statement is not what blocks the competing writer - it is how a test makes
    the holder's transaction describe a real conflicting change, which is what
    the code under test would have to serialise against in production.

    Autocommit is off at the driver level (``isolation_level=None``) so the
    ``BEGIN`` here is the only transaction on this connection and the driver
    never ends it behind the test's back.
    """
    holder = sqlite3.connect(store, isolation_level=None, timeout=lock_wait_ms / 1000)
    try:
        holder.execute(f"PRAGMA busy_timeout={lock_wait_ms}")
        holder.execute("BEGIN IMMEDIATE")
        if statement is not None:
            holder.execute(statement, tuple(parameters))
        yield holder
    finally:
        holder.rollback()
        holder.close()
