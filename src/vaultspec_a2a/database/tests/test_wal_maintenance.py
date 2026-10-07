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

Every test drives real SQLite files, and the reclaim verb runs as the real
``vaultspec-a2a migrate --compact`` in a real subprocess.  Its listener guard is
proven against a real loopback listener and against a real gateway.
"""

from __future__ import annotations

import http.server
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ...desktop.profile import derive_state_paths
from ...testing import (
    DEFAULT_ATTACH_CREDENTIAL,
    LOOPBACK_TIMEOUT,
    JsonReplyHandler,
    booted_gateway,
    broker_gateway_env,
    free_port,
    gateway_script,
    run_cli,
    seat_app_home,
    serve_handler,
)
from ...tests._write_authority import make_test_thread_authority_columns
from ..models import Base, ControlActionModel, ThreadModel
from ..session import (
    CheckpointMode,
    WalCheckpointResult,
    checkpoint_wal,
    close_db,
    init_db,
    inspect_sqlite_database,
    seat_sqlite_posture,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Mapping
    from pathlib import Path

# WAL evidence depends on pages written, not on the number of commits. A larger
# row reaches the same multi-megabyte/page-count thresholds with far fewer
# fsync-heavy autocommits, which matters especially on Windows.
_PAYLOAD = "x" * (16 * 1024)


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
    # These tests inspect WAL/checkpoint behaviour, not power-loss durability.
    # Avoid an fsync for every intentionally separate autocommit while retaining
    # real files, transactions, readers, frames, and checkpoint operations.
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA busy_timeout=50")
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
    await close_db()
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


@pytest.mark.asyncio
async def test_migrating_initialisation_leaves_the_store_in_wal_on_disk(
    runtime_dir: Path,
) -> None:
    """A store fresh from migration is WAL on disk once ``init_db`` returns.

    Migration leaves a new store on SQLite's default rollback journal, and WAL is
    requested per connection. The gateway's boot-time storage diagnostics read
    the file through a connection of their own right after initialisation, so
    unless initialisation put WAL into the file header they report "WAL
    unavailable" for a store that is about to run in WAL.
    """
    database = runtime_dir / "fresh.db"
    # A leaked engine singleton would make init_db ignore ``database``.
    await close_db()
    try:
        await init_db(database)
        diagnostics = inspect_sqlite_database(database)
    finally:
        await close_db()

    assert diagnostics["journal_mode"] == "wal"
    assert diagnostics["wal_enabled"] is True


@pytest.mark.asyncio
async def test_non_migrating_initialisation_leaves_the_store_untouched(
    runtime_dir: Path,
) -> None:
    """Without migration, the store keeps its mode until the caller seats it.

    The desktop boot validates a seated store before it touches it, so
    initialisation must not rewrite the header of a store that validation may
    still refuse. Seating the posture afterwards is the caller's explicit act.
    """
    database = runtime_dir / "seated.db"
    seed = sqlite3.connect(database)
    try:
        seed.execute("CREATE TABLE seed (id INTEGER PRIMARY KEY)")
        seed.commit()
    finally:
        seed.close()

    await close_db()
    try:
        engine = await init_db(database, apply_migrations=False)
        untouched = inspect_sqlite_database(database)["journal_mode"]
        await seat_sqlite_posture(engine)
        seated = inspect_sqlite_database(database)["journal_mode"]
    finally:
        await close_db()

    assert untouched == "delete"
    assert seated == "wal"


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
        sizes: list[int] = []
        for _ in range(5):
            _churn(conn, 320)
            sizes.append(_wal_bytes(database))
    finally:
        conn.close()

    assert pages > 0
    # Generous headroom over the ceiling: a checkpoint resets the log only at a
    # commit boundary, so it overshoots slightly rather than capping exactly.
    ceiling = pages * page_size * 2
    assert max(sizes) < ceiling, sizes
    # Five batches each cross the page ceiling, and the last is no larger than
    # the first: growth has stopped, it has not merely slowed.
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
        _churn(conn, 320)
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
        _churn(writer, 50)
        reader.execute("SELECT count(*) FROM churn").fetchone()
        assert reader.in_transaction is False

        _churn(writer, 320)
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
        _churn(writer, 20)

        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM churn").fetchone()
        assert reader.in_transaction is True

        _churn(writer, 320)
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

    Which is the operation ``migrate --compact`` already performs on demand, so
    enabling ``auto_vacuum`` would buy nothing that path does not already give -
    at the price of page moves on every commit.
    """
    database = runtime_dir / "needs-vacuum.db"
    conn = _open_wal_database(database)
    try:
        _churn(conn, 50)
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
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        _churn(conn, 400)
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
# The reclaim verb
# ---------------------------------------------------------------------------

_GATEWAY_PORT_ENV = "VAULTSPEC_A2A_PORT"
_WORKER_PORT_ENV = "VAULTSPEC_A2A_WORKER_PORT"


def _verb_env(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the environment a ``migrate`` child runs under in these tests.

    Both configured service ports point at free ports, because ``--compact``
    refuses while anything listens on either one, and a child left on the
    defaults would refuse whenever a development service runs on this host. The
    blocked-checkpoint proof needs a nonzero wait, not the production default's
    five seconds of idle time, and the compaction connection honors the same
    setting as every other SQLite connection authority.
    """
    env = {
        _GATEWAY_PORT_ENV: str(free_port()),
        _WORKER_PORT_ENV: str(free_port()),
        "VAULTSPEC_A2A_SQLITE_BUSY_TIMEOUT_MS": "50",
    }
    if overrides is not None:
        env.update(overrides)
    return env


def _migrate(
    home: Path, *flags: str, env: Mapping[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    """Run ``vaultspec-a2a migrate`` against *home* and parse its JSON result."""
    result = run_cli("migrate", "--app-home", str(home), *flags, env=_verb_env(env))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"migrate printed no JSON result (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        ) from exc
    assert isinstance(payload, dict), result.stdout
    return result, cast("dict[str, object]", payload)


def _seat_wal_mode(database: Path) -> None:
    """Put the migrated database into WAL mode, as the gateway's first connect does.

    The migrate verb builds its own engine without the application connect
    listener, so a freshly migrated file is still on a rollback journal.  Seating
    WAL here is what makes the tests below exercise the write-ahead log at all -
    and, in rollback mode, a held read transaction takes a shared lock that
    blocks writers outright, which is a different failure from the one under
    test.
    """
    conn = sqlite3.connect(str(database), isolation_level=None)
    try:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    finally:
        conn.close()


def _migrated_home(base: Path) -> tuple[Path, Path]:
    """Migrate a fresh application home; return it and its primary store in WAL."""
    home = base / "app"
    result, payload = _migrate(home)
    assert payload["status"] == "succeeded", (payload, result.stderr)
    database = derive_state_paths(home).database_path
    _seat_wal_mode(database)
    return home, database


def _write_threads(database: Path, count: int) -> None:
    """Commit ``count`` real rows through the production models, one per commit."""
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA synchronous=OFF")
        with Session(engine) as session:
            for index in range(count):
                authority = make_test_thread_authority_columns()
                session.add(
                    ThreadModel(
                        **authority,
                        id=f"t{index}",
                        status="running",
                    )
                )
                session.add(
                    ControlActionModel(
                        id=f"action-t{index}",
                        thread_id=f"t{index}",
                        action_type=str(authority["writer_action_type"]),
                        idempotency_key=f"ingest-t{index}",
                        dispatch_id=str(authority["writer_action_receipt_id"]),
                        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
                    )
                )
                session.commit()
    finally:
        engine.dispose()


def test_migrate_compact_reclaims_the_log_and_reports_success(
    runtime_dir: Path,
) -> None:
    """The ordinary path: a real log is truncated away, and success says so.

    An idle connection is held open for the duration, for two reasons: SQLite
    removes the ``-wal`` file entirely when the last connection closes, which
    would leave this test reclaiming nothing and passing anyway; and an idle
    reader holds no snapshot, so the reclaim is proven not to need a store that
    nobody has open.  The configured ports are free, so this is also the case in
    which the listener guard lets the verb proceed.
    """
    home, database = _migrated_home(runtime_dir)

    holder = sqlite3.connect(str(database), isolation_level=None)
    try:
        holder.execute("SELECT count(*) FROM threads").fetchone()
        assert holder.in_transaction is False

        _write_threads(database, 128)
        grown = _wal_bytes(database)

        result, payload = _migrate(home, "--compact")
        reclaimed = _wal_bytes(database)
    finally:
        holder.close()

    # Asserted before the outcome so a database that never built a log cannot
    # make this test pass by reclaiming nothing.
    assert grown > 0, "no write-ahead log was produced to reclaim"
    assert result.returncode == 0, (payload, result.stderr)
    assert payload["status"] == "succeeded"
    assert payload["failed_stage"] is None
    # Not zero: the checkpoint truncates the log, and then VACUUM rewrites the
    # whole database through that same log, leaving its own frames behind.  What
    # the verb promises is that the accumulated log is gone, which is the
    # order-of-magnitude drop asserted here rather than an empty file.
    assert reclaimed < grown / 2, (grown, reclaimed)


def test_migrate_compact_reports_a_blocked_checkpoint_instead_of_announcing_success(
    runtime_dir: Path,
) -> None:
    """The reclaim path must not report completion when it reclaimed nothing.

    This is the defect the verb guards against: a checkpoint's result row
    discarded and completion announced unconditionally, so an operator
    investigating a growing database is told the one path that returns space ran
    cleanly - while a held read transaction meant it had done nothing at all.
    """
    home, database = _migrated_home(runtime_dir)

    reader = sqlite3.connect(str(database), isolation_level=None)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM threads").fetchone()

        _write_threads(database, 128)

        pinned_size = _wal_bytes(database)
        result, payload = _migrate(home, "--compact")
        size_after = _wal_bytes(database)
    finally:
        reader.close()

    assert pinned_size > 0, "the reader failed to pin any log frames"
    assert result.returncode == 1, payload
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "compact"
    assert payload["error_class"] == "CompactionBlockedError"
    detail = str(payload["detail"])
    assert "WAL checkpoint blocked" in detail
    assert "VACUUM skipped" in detail
    # The log is exactly as large as it was: the report matches reality.
    assert size_after == pinned_size


class _UnauthorizedHandler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
    """Answers every request 401, as an authenticated gateway answers a probe.

    A guard that treats any HTTP error as "not running" reads a gateway with
    tokens configured - which refuses an unauthenticated health request - as
    stopped, and goes on to rewrite the store the gateway still holds open.
    """

    def do_GET(self) -> None:
        """Refuse the request the way an authenticated gateway does."""
        self._reply(401, {"detail": "unauthorized"})


@pytest.mark.parametrize("held_port_env", [_GATEWAY_PORT_ENV, _WORKER_PORT_ENV])
def test_migrate_compact_refuses_while_an_authenticated_service_holds_a_port(
    runtime_dir: Path, held_port_env: str
) -> None:
    """A 401 answer is a running service, not an absent one."""
    home, database = _migrated_home(runtime_dir)

    holder = sqlite3.connect(str(database), isolation_level=None)
    try:
        # A connection that has never run a statement has not attached to the
        # log, so the writer closing last would checkpoint it away; the service
        # this stands in for holds the store open, so the holder reads once.
        holder.execute("SELECT count(*) FROM threads").fetchone()
        _write_threads(database, 16)
        grown = _wal_bytes(database)

        with serve_handler(_UnauthorizedHandler) as held_port:
            result, payload = _migrate(
                home, "--compact", env={held_port_env: str(held_port)}
            )
        size_after = _wal_bytes(database)
    finally:
        holder.close()

    assert grown > 0, "no write-ahead log was produced to protect"
    assert result.returncode == 1, payload
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "lock"
    assert payload["error_class"] == "StoreLockedError"
    assert f"listening on port {held_port}" in str(payload["detail"])
    assert payload["stores"] == []
    # Refused before any store was touched: the log was never checkpointed.
    assert size_after == grown


@pytest.mark.resource("desktop-processes", shared=True)
def test_migrate_compact_refuses_while_a_real_gateway_holds_the_store(
    tmp_path: Path,
) -> None:
    """A live authenticated gateway over the home refuses compaction at ``lock``.

    The lock probe alone would admit this run: a gateway between requests holds
    no lock on its store, so ``BEGIN IMMEDIATE`` succeeds beside it.  Only the
    listener guard stands between the verb and a VACUUM under a live service, so
    it is proven against the real product as well as against a bare listener.
    """
    app_home = tmp_path / "app-home"
    seat_app_home(app_home)
    with booted_gateway(
        broker_gateway_env(app_home, gateway_token=DEFAULT_ATTACH_CREDENTIAL),
        log_path=tmp_path / "gateway.log",
        script=gateway_script(log_level="warning"),
    ) as gateway:
        result, payload = _migrate(
            app_home,
            "--compact",
            env={
                _GATEWAY_PORT_ENV: str(gateway.gateway_port),
                _WORKER_PORT_ENV: str(gateway.worker_port),
            },
        )
        health = httpx.get(f"{gateway.base_url}/health", timeout=LOOPBACK_TIMEOUT)

    assert result.returncode == 1, payload
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "lock"
    assert payload["error_class"] == "StoreLockedError"
    assert f"listening on port {gateway.gateway_port}" in str(payload["detail"])
    assert payload["stores"] == []
    # The refusal left the service it detected serving.
    assert health.status_code == 200


def test_the_models_the_reclaim_test_writes_are_the_production_models() -> None:
    """Guards the tests above against drifting onto a hand-rolled table."""
    assert ThreadModel.__tablename__ in Base.metadata.tables
