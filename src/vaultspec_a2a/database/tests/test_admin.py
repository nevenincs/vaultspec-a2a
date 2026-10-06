"""A clear that reports success must actually have cleared everything.

The truncation path covered four of nine application tables and no checkpoint
state, then printed a count and exited zero. An operator running it to reset a
machine kept every control action, permission request, queued task, execution
state row, the authoring cursor, and the entire conversation history - while
being told the database was cleared. Incomplete truncation that announces
completion is worse than none, because it stops the operator looking.

These tests build a real SQLite database from the production metadata, populate
every table through the real models, and assert on what survives.
"""

from __future__ import annotations

import http.server
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, inspect, text

from ...testing.ports import free_port
from ...testing.tests._support.http_handlers import JsonReplyHandler
from ...testing.tests._support.listeners import serve_handler
from ...tests._write_authority import make_test_thread_authority_columns
from ..admin import _CHECKPOINT_TABLES, _CLEAR_ORDER, _administrative_engine
from ..models import (
    ArtifactModel,
    Base,
    ControlActionModel,
    ThreadModel,
)
from ._admin_cli import run_admin

if TYPE_CHECKING:
    from pathlib import Path


def test_the_clear_order_covers_every_application_table() -> None:
    """A table absent from the order is one a clear silently leaves behind."""
    declared = set(Base.metadata.tables)

    assert declared == set(_CLEAR_ORDER), declared.symmetric_difference(_CLEAR_ORDER)


def test_children_are_cleared_before_the_thread_they_reference() -> None:
    """Deleting the parent first is refused wherever foreign keys are enforced."""
    position = {table: index for index, table in enumerate(_CLEAR_ORDER)}

    for table_name, table in Base.metadata.tables.items():
        for constraint in table.foreign_keys:
            referenced = constraint.column.table.name
            if referenced == table_name:
                continue
            assert position[table_name] < position[referenced], (
                f"{table_name} must be cleared before {referenced}"
            )


def test_every_table_is_emptied_against_a_real_database(tmp_path: Path) -> None:
    """The truncation empties real rows in a real database, in a valid order.

    Rows are built through the production models rather than hand-written SQL, so
    the fixture cannot drift from the schema it is meant to exercise.
    """
    from sqlalchemy.orm import Session

    database = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            ThreadModel(
                **make_test_thread_authority_columns(), id="t1", status="running"
            )
        )
        session.flush()
        session.add(ArtifactModel(id="a1", thread_id="t1", type="file", path="x.txt"))
        session.add(
            ControlActionModel(
                id="c1",
                thread_id="t1",
                action_type="cancel",
                idempotency_key="k1",
                recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        session.commit()

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM threads")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM artifacts")).scalar_one() == 1

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        for table in _CLEAR_ORDER:
            conn.execute(text(f"DELETE FROM {table}"))

    with engine.connect() as conn:
        for table in _CLEAR_ORDER:
            remaining = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            assert remaining == 0, f"{table} still holds {remaining} row(s)"
    engine.dispose()


def test_the_checkpoint_tables_are_named_and_child_first() -> None:
    """Checkpoint writes reference their checkpoint, so writes clear first."""
    assert _CHECKPOINT_TABLES.index("writes") < _CHECKPOINT_TABLES.index("checkpoints")


def test_a_database_without_checkpoint_tables_is_tolerated(tmp_path: Path) -> None:
    """A fresh install has no checkpoint tables; that is not an error."""
    database = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)

    present = set(inspect(engine).get_table_names())

    assert not present.intersection(_CHECKPOINT_TABLES)
    engine.dispose()


def test_the_administrative_engine_enforces_foreign_keys(tmp_path: Path) -> None:
    """The destructive path gets the safety net the application engine has.

    ``foreign_keys`` is per-connection and OFF by default, so the truncation
    engine used to run without it: a wrong delete order would have orphaned child
    rows silently instead of being refused. The previous version of this suite
    had to issue the pragma itself, which was the tell.
    """
    database = tmp_path / "pragma.db"
    engine = _administrative_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert conn.execute(text("PRAGMA busy_timeout")).scalar_one() > 0
    finally:
        engine.dispose()


def test_foreign_keys_are_enforced_against_a_real_violation(tmp_path: Path) -> None:
    """The pragma is load-bearing: a parent-first delete must be refused.

    Asserting the pragma reads back as ``1`` proves it was set; this proves it
    does something. Without it SQLite accepts the delete and leaves the child
    row pointing at a thread that no longer exists.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    database = tmp_path / "violation.db"
    setup = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(setup)
    with Session(setup) as session:
        session.add(
            ThreadModel(
                **make_test_thread_authority_columns(), id="t1", status="running"
            )
        )
        session.flush()
        session.add(ArtifactModel(id="a1", thread_id="t1", type="file", path="x.txt"))
        session.commit()
    setup.dispose()

    engine = _administrative_engine(f"sqlite:///{database}")
    try:
        raised = False
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM threads"))
        except IntegrityError:
            raised = True
        assert raised, "deleting a referenced parent was not refused"
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Destructive verbs refuse while a service holds a configured port
# ---------------------------------------------------------------------------


class _UnauthorizedHandler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
    """Answers every request 401, as an authenticated gateway answers a probe.

    The destructive-verb guard used to treat any HTTP error as "not running",
    so a gateway with tokens configured - which refuses an unauthenticated
    health request - looked stopped and the restore overwrote its live store.
    """

    def do_GET(self) -> None:
        """Refuse the request the way an authenticated gateway does."""
        self._reply(401, {"detail": "unauthorized"})


_GATEWAY_PORT_ENV = "VAULTSPEC_A2A_PORT"
_WORKER_PORT_ENV = "VAULTSPEC_A2A_WORKER_PORT"


def _seed_store(directory: Path) -> tuple[Path, str]:
    """Write a one-row live store and a snapshot of different content beside it.

    Returns the live database path and the snapshot's file name, so a test can
    tell from the live row afterwards whether a restore ran.
    """
    database = directory / "app.db"
    snapshot = directory / "app.snapshot.seeded"
    for path, marker in ((database, "live"), (snapshot, "snapshot")):
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
            conn.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
            conn.commit()
        finally:
            conn.close()
    return database, snapshot.name


def _marker(database: Path) -> str:
    """Return the single marker row a seeded store carries."""
    conn = sqlite3.connect(str(database))
    try:
        return str(conn.execute("SELECT value FROM marker").fetchone()[0])
    finally:
        conn.close()


@pytest.mark.parametrize("held_port_env", [_GATEWAY_PORT_ENV, _WORKER_PORT_ENV])
def test_restore_refuses_while_an_authenticated_service_holds_a_port(
    tmp_path: Path, held_port_env: str
) -> None:
    """A 401 answer is a running service, not an absent one."""
    database, snapshot_name = _seed_store(tmp_path)
    ports = {_GATEWAY_PORT_ENV: str(free_port()), _WORKER_PORT_ENV: str(free_port())}

    with serve_handler(_UnauthorizedHandler) as held_port:
        ports[held_port_env] = str(held_port)
        result = run_admin(
            database, "restore", "--name", snapshot_name, "--yes", env=ports
        )

    assert result.returncode == 1, result.stderr
    assert f"listening on port {ports[held_port_env]}" in result.stderr
    assert _marker(database) == "live"


def test_clear_refuses_while_an_authenticated_service_holds_a_port(
    tmp_path: Path,
) -> None:
    """Clearing a store a service holds open is the same hazard as restoring it."""
    database, _ = _seed_store(tmp_path)

    with serve_handler(_UnauthorizedHandler) as held_port:
        result = run_admin(
            database,
            "clear",
            "--yes",
            env={
                _GATEWAY_PORT_ENV: str(held_port),
                _WORKER_PORT_ENV: str(free_port()),
            },
        )

    assert result.returncode == 1, result.stderr
    assert f"listening on port {held_port}" in result.stderr
    assert _marker(database) == "live"


def test_restore_proceeds_when_no_service_listens(tmp_path: Path) -> None:
    """The guard refuses a held port, not every restore."""
    database, snapshot_name = _seed_store(tmp_path)

    result = run_admin(
        database,
        "restore",
        "--name",
        snapshot_name,
        "--yes",
        env={_GATEWAY_PORT_ENV: str(free_port()), _WORKER_PORT_ENV: str(free_port())},
    )

    assert result.returncode == 0, result.stderr
    assert _marker(database) == "snapshot"
