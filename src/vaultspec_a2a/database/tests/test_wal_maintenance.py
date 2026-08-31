"""SQLite space reclamation: what bounds the write-ahead log, and what does not.

The concern these tests close is that a long-lived install grows on disk and
nothing ever gives the space back.  Two claims were made about why, and only one
of them survives contact with real SQLite:

* The write-ahead log has no ceiling because the gateway holds a process-lifetime
  reader open.  This is FALSE for an idle reader, and the tests below pin the
  distinction: a connection that is merely open does not hold a snapshot, and the
  log settles at the autocheckpoint ceiling.  A connection sitting in an OPEN READ
  TRANSACTION is the real hazard - it pins every frame written after it, no
  autocheckpoint value can reset the log, and the file then grows linearly for as
  long as the transaction is held.
* ``auto_vacuum`` should be enabled.  It cannot be, and would not pay: the connect
  posture sets ``journal_mode=WAL`` first, which writes the database header and
  fixes ``auto_vacuum`` at NONE for the life of the file.  A later pragma is
  accepted and silently does nothing.  These tests hold both facts against real
  SQLite so the decision recorded in ``session.py`` is checked rather than
  asserted.

Every test drives real SQLite files and the real administrative CLI in a real
subprocess.  Nothing here is simulated.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ..models import Base, ThreadModel
from ..session import (
    CheckpointMode,
    WalCheckpointResult,
    checkpoint_wal,
    close_db,
    init_db,
)

if TYPE_CHECKING:
    from pathlib import Path

_PAYLOAD = "x" * 2000


def _wal_bytes(database: Path) -> int:
    """Return the size of the database's write-ahead log, zero when absent."""
    log = database.with_name(database.name + "-wal")
    return log.stat().st_size if log.exists() else 0


def _open_wal_database(
    database: Path, *, autocheckpoint: int | None = None
) -> sqlite3.Connection:
    """Open a real WAL-mode SQLite connection with a table to churn."""
    conn = sqlite3.connect(str(database), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    if autocheckpoint is not None:
        conn.execute(f"PRAGMA wal_autocheckpoint={autocheckpoint:d}")
    conn.execute("CREATE TABLE IF NOT EXISTS churn (id INTEGER PRIMARY KEY, blob TEXT)")
    return conn


def _churn(conn: sqlite3.Connection, rows: int) -> None:
    """Commit ``rows`` individual inserts, one write-ahead log frame at a time."""
    for _ in range(rows):
        conn.execute("INSERT INTO churn (blob) VALUES (?)", (_PAYLOAD,))


# ---------------------------------------------------------------------------
# The connect posture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_production_engine_leaves_the_log_bounded(runtime_dir: Path) -> None:
    """The engine the service actually builds is in WAL with a live ceiling.

    Asserted through ``init_db`` rather than by calling the connect listener
    directly: the listener is only worth anything if it is still attached to the
    engine the gateway uses, and a direct call would pass even if the
    ``event.listen`` registration were dropped.

    The autocheckpoint assertion is a guard rather than a claim of authorship -
    nothing here sets it, and the point is that nothing may set it to zero, which
    is the one value that would leave the log genuinely unbounded.
    """
    database = runtime_dir / "posture.db"
    try:
        engine = await init_db(database)
        async with engine.connect() as conn:
            autocheckpoint = (
                await conn.execute(text("PRAGMA wal_autocheckpoint"))
            ).scalar_one()
            journal_mode = (
                await conn.execute(text("PRAGMA journal_mode"))
            ).scalar_one()
    finally:
        await close_db()

    assert journal_mode == "wal"
    assert autocheckpoint > 0, "a zero autocheckpoint leaves the log unbounded"


def test_sustained_writes_settle_at_the_ceiling_rather_than_growing(
    runtime_dir: Path,
) -> None:
    """With no reader holding a snapshot, the log plateaus instead of climbing.

    This is the measurement that refutes "the log has no practical ceiling" for
    the ordinary case, and the reason the connect posture sets no autocheckpoint
    of its own: SQLite's default is already a working ceiling.  The checkpoint
    resets the log in place, so the file stops growing even though nothing ever
    truncates it.
    """
    database = runtime_dir / "plateau.db"
    conn = _open_wal_database(database)
    try:
        # Read the ceiling from SQLite rather than restating it, so the test
        # measures the behaviour actually in force on this build.
        pages = conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        sizes = []
        for _ in range(5):
            _churn(conn, 1200)
            sizes.append(_wal_bytes(database))
    finally:
        conn.close()

    assert pages > 0
    # Generous headroom over the ceiling: a checkpoint resets the log only at a
    # commit boundary, so it overshoots slightly rather than capping exactly.
    ceiling = pages * page_size * 2
    assert max(sizes) < ceiling, sizes
    # 6,000 committed rows across five batches, and the last batch is no larger
    # than the first: growth has stopped, it has not merely slowed.
    assert sizes[-1] <= sizes[0] * 1.1, sizes


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------


def test_a_truncating_checkpoint_returns_the_log_to_the_filesystem(
    runtime_dir: Path,
) -> None:
    """Grow the log, checkpoint it, and prove the file shrank."""
    database = runtime_dir / "truncate.db"
    # Autocheckpoint off so the log is allowed to grow to something worth
    # reclaiming; this is the condition a pinned reader produces in production.
    conn = _open_wal_database(database, autocheckpoint=0)
    try:
        _churn(conn, 3000)
        grown = _wal_bytes(database)

        result = checkpoint_wal(conn)

        reclaimed = _wal_bytes(database)
    finally:
        conn.close()

    assert grown > 4 * 1024 * 1024, f"log did not grow enough to be meaningful: {grown}"
    assert result.blocked is False
    assert result.fully_checkpointed
    assert reclaimed == 0
    assert reclaimed < grown


def test_an_idle_open_reader_does_not_prevent_reclamation(runtime_dir: Path) -> None:
    """A connection that is merely open holds no snapshot and blocks nothing.

    The gateway's process-lifetime read-only checkpointer is this case: it runs a
    query and returns to idle, leaving no read transaction behind.
    """
    database = runtime_dir / "idle-reader.db"
    writer = _open_wal_database(database, autocheckpoint=0)
    reader = sqlite3.connect(str(database), isolation_level=None)
    try:
        _churn(writer, 500)
        reader.execute("SELECT count(*) FROM churn").fetchone()
        assert reader.in_transaction is False

        _churn(writer, 2000)
        grown = _wal_bytes(database)
        result = checkpoint_wal(writer)
        reclaimed = _wal_bytes(database)
    finally:
        reader.close()
        writer.close()

    assert grown > 0
    assert result.blocked is False
    assert result.fully_checkpointed
    assert reclaimed == 0


def test_an_open_read_transaction_pins_the_log_and_the_block_is_reported(
    runtime_dir: Path,
) -> None:
    """The real hazard: a held read transaction, and a checkpoint that says so.

    SQLite reports this by returning ``busy=1`` from a statement that otherwise
    succeeds.  A caller discarding that row cannot distinguish a truncated log
    from an untouched one, which is exactly how a reclaim path comes to report
    success while reclaiming nothing.
    """
    database = runtime_dir / "pinned.db"
    writer = _open_wal_database(database, autocheckpoint=0)
    reader = sqlite3.connect(str(database), isolation_level=None)
    try:
        _churn(writer, 200)

        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM churn").fetchone()
        assert reader.in_transaction is True

        _churn(writer, 3000)
        pinned_size = _wal_bytes(database)

        blocked = checkpoint_wal(writer)
        size_after_blocked = _wal_bytes(database)

        reader.execute("COMMIT")
        released = checkpoint_wal(writer)
        size_after_release = _wal_bytes(database)
    finally:
        reader.close()
        writer.close()

    assert pinned_size > 4 * 1024 * 1024, pinned_size
    assert blocked.blocked is True
    assert blocked.fully_checkpointed is False
    # The decisive assertion: the checkpoint did not raise, and it did not work.
    assert size_after_blocked == pinned_size

    assert released.blocked is False
    assert size_after_release == 0


def test_a_database_with_no_log_is_a_successful_no_op(runtime_dir: Path) -> None:
    """A non-WAL database reports -1 page counts, which is not a failure."""
    database = runtime_dir / "rollback.db"
    conn = sqlite3.connect(str(database), isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

        result = checkpoint_wal(conn)
    finally:
        conn.close()

    assert result.blocked is False
    assert result.log_pages == -1


def test_an_unknown_checkpoint_mode_is_refused(runtime_dir: Path) -> None:
    """The mode reaches the statement by interpolation, so it is checked first.

    The annotation already excludes this value, which is why the injected mode is
    cast in deliberately: the runtime guard is what stands between an untyped
    caller and a PRAGMA built by string interpolation, and a guard no test
    reaches is one a later refactor can delete unnoticed.
    """
    database = runtime_dir / "mode.db"
    conn = _open_wal_database(database)
    try:
        injected = cast("CheckpointMode", "TRUNCATE; DROP TABLE churn")
        with pytest.raises(ValueError, match="checkpoint mode"):
            checkpoint_wal(conn, mode=injected)

        assert conn.execute("SELECT count(*) FROM churn").fetchone() is not None
    finally:
        conn.close()


def test_the_result_reports_a_partial_checkpoint_as_incomplete() -> None:
    """A checkpoint that wrote back less than the log holds is not complete."""
    partial = WalCheckpointResult(blocked=True, log_pages=20250, checkpointed_pages=1)

    assert partial.fully_checkpointed is False


# ---------------------------------------------------------------------------
# The auto_vacuum decision
# ---------------------------------------------------------------------------


def test_enabling_auto_vacuum_after_wal_mode_is_silently_ignored(
    runtime_dir: Path,
) -> None:
    """The connect posture's own first statement forecloses ``auto_vacuum``.

    ``journal_mode=WAL`` writes the database header; from then on ``auto_vacuum``
    is fixed for the life of the file and the pragma below is accepted while
    changing nothing.  This is why the connect listener does not attempt it: the
    statement would read as a working setting and never take effect.
    """
    database = runtime_dir / "after-wal.db"
    conn = sqlite3.connect(str(database), isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")

        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0
    finally:
        conn.close()


def test_auto_vacuum_requires_a_full_vacuum_to_change_on_an_existing_database(
    runtime_dir: Path,
) -> None:
    """Enabling it on any existing install means rewriting the whole file.

    Which is the operation ``migrate --fix`` already performs on demand, so
    enabling ``auto_vacuum`` would buy nothing that path does not already give -
    at the price of page moves on every commit.
    """
    database = runtime_dir / "needs-vacuum.db"
    conn = _open_wal_database(database)
    try:
        _churn(conn, 200)
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0

        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 0, (
            "pragma alone must not appear to work"
        )

        conn.execute("VACUUM")
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    finally:
        conn.close()


def test_incremental_vacuum_reclaims_far_less_than_a_full_vacuum(
    runtime_dir: Path,
) -> None:
    """Even with ``auto_vacuum`` genuinely in force, incremental reclaim is token.

    Measured on a store whose every row has been deleted: ``incremental_vacuum``
    returns a single page while a full ``VACUUM`` returns essentially the whole
    file.  This is the other half of the reason the connect posture leaves
    ``auto_vacuum`` alone.
    """
    database = runtime_dir / "incremental.db"
    conn = sqlite3.connect(str(database), isolation_level=None)
    try:
        # Set before the header exists, which is the only point it can be set.
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("CREATE TABLE churn (id INTEGER PRIMARY KEY, blob TEXT)")
        _churn(conn, 2500)
        conn.execute("PRAGMA journal_mode=WAL")
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2

        checkpoint_wal(conn)
        grown = database.stat().st_size

        conn.execute("DELETE FROM churn")
        checkpoint_wal(conn)
        after_delete = database.stat().st_size
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] > 1000

        conn.execute("PRAGMA incremental_vacuum")
        checkpoint_wal(conn)
        after_incremental = database.stat().st_size

        conn.execute("VACUUM")
        checkpoint_wal(conn)
        after_full = database.stat().st_size
    finally:
        conn.close()

    assert grown > 4 * 1024 * 1024, grown
    # Deleting every row returns nothing on its own: the pages go on the freelist.
    assert after_delete == grown
    incremental_reclaimed = after_delete - after_incremental
    full_reclaimed = after_delete - after_full
    assert incremental_reclaimed < after_delete * 0.01, incremental_reclaimed
    assert full_reclaimed > after_delete * 0.9, full_reclaimed


# ---------------------------------------------------------------------------
# The administrative reclaim verb
# ---------------------------------------------------------------------------


def _run_admin(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real administrative CLI against ``database`` in a subprocess.

    A subprocess rather than an in-process call because the verb reads the
    process-wide settings singleton: configuring a child through its environment
    exercises the real configuration path, where reaching into the singleton
    would only prove that the singleton can be overwritten.
    """
    env = dict(os.environ)
    env["VAULTSPEC_DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "vaultspec_a2a.database.admin", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )


def _seat_wal_mode(database: Path) -> None:
    """Put the migrated database into WAL mode, as the gateway's first connect does.

    The migration path builds its own synchronous engine and does not carry the
    application connect listener, so a freshly migrated file is still on a
    rollback journal.  Seating WAL here is what makes the tests below exercise
    the write-ahead log at all - and, in rollback mode, a held read transaction
    takes a shared lock that blocks writers outright, which is a different
    failure from the one under test.
    """
    conn = sqlite3.connect(str(database), isolation_level=None)
    try:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    finally:
        conn.close()


def _write_threads(database: Path, count: int) -> None:
    """Commit ``count`` real rows through the production models, one per commit."""
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            for index in range(count):
                session.add(ThreadModel(id=f"t{index}", status="running"))
                session.commit()
    finally:
        engine.dispose()


def test_migrate_fix_reclaims_the_log_and_reports_success(runtime_dir: Path) -> None:
    """The ordinary path: a real log is truncated away, and exit zero says so.

    An idle connection is held open for the duration, for two reasons: SQLite
    removes the ``-wal`` file entirely when the last connection closes, which
    would leave this test reclaiming nothing and passing anyway; and an
    idle-but-open reader is the shape the running gateway actually has, so the
    reclaim is proven against it rather than against a quiesced database.
    """
    database = runtime_dir / "reclaim.db"
    assert _run_admin(database, "migrate").returncode == 0
    _seat_wal_mode(database)

    holder = sqlite3.connect(str(database), isolation_level=None)
    try:
        holder.execute("SELECT count(*) FROM threads").fetchone()
        assert holder.in_transaction is False

        _write_threads(database, 800)
        grown = _wal_bytes(database)

        result = _run_admin(database, "migrate", "--fix")
        reclaimed = _wal_bytes(database)
    finally:
        holder.close()

    # Asserted before the outcome so a database that never built a log cannot
    # make this test pass by reclaiming nothing.
    assert grown > 0, "no write-ahead log was produced to reclaim"
    assert result.returncode == 0, result.stderr
    assert "WAL checkpoint and VACUUM complete." in result.stdout
    # Not zero: the checkpoint truncates the log, and then VACUUM rewrites the
    # whole database through that same log, leaving its own frames behind.  What
    # the verb promises is that the accumulated log is gone, which is the
    # order-of-magnitude drop asserted here rather than an empty file.
    assert reclaimed < grown / 2, (grown, reclaimed)


def test_migrate_fix_reports_a_blocked_checkpoint_instead_of_announcing_success(
    runtime_dir: Path,
) -> None:
    """The reclaim path must not report completion when it reclaimed nothing.

    This is the defect: the checkpoint's result row was discarded and
    "WAL checkpoint and VACUUM complete." was printed unconditionally, so an
    operator investigating a growing database was told the one path that returns
    space had run cleanly - while a held read transaction meant it had done
    nothing at all.
    """
    database = runtime_dir / "blocked.db"
    assert _run_admin(database, "migrate").returncode == 0
    _seat_wal_mode(database)

    reader = sqlite3.connect(str(database), isolation_level=None)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM threads").fetchone()

        _write_threads(database, 800)

        pinned_size = _wal_bytes(database)
        result = _run_admin(database, "migrate", "--fix")
        size_after = _wal_bytes(database)
    finally:
        reader.close()

    assert pinned_size > 0, "the reader failed to pin any log frames"
    assert result.returncode == 1, result.stdout
    assert "WAL checkpoint blocked" in result.stderr
    assert "VACUUM skipped" in result.stderr
    assert "complete." not in result.stdout
    # The log is exactly as large as it was: the report matches reality.
    assert size_after == pinned_size


def test_the_models_the_reclaim_test_writes_are_the_production_models() -> None:
    """Guards the test above against drifting onto a hand-rolled table."""
    assert ThreadModel.__tablename__ in Base.metadata.tables
