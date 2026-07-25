"""Certify durable cross-store run deletion through the real public facade.

Deletion is the one product operation that must reach BOTH real stores: the
SQLite control row and the SQLite checkpoint artifacts. These scenarios create a
real run that genuinely checkpoints, delete it through the attach-gated product
facade, and prove convergence on both stores directly - the control store via
the public surface (status 404, absent from discovery, product state 404) and
the checkpoint store by reading the real checkpoint database file the worker
wrote to. The before/after checkpoint counts are the discriminator: a deletion
that silently skipped the checkpoint store would leave the "after" count above
zero and fail here.

The interrupted-saga crash-recovery internals - a cleanup item failing and a
replay resuming the same durable saga - are proven against real control and
checkpoint stores by the control/api suites; they cannot be induced through this
black-box facade without forbidden fault injection, so this certifies the
facade-observable convergence: a completed deletion is final and a replayed
delete converges rather than starting a second teardown or erroring.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from ...desktop.profile import derive_state_paths
from .conftest import wait_for_terminal

if TYPE_CHECKING:
    from pathlib import Path

    from .. import CertifiedGateway


def _checkpoint_rows_for(app_home: Path, thread_id: str) -> int:
    """Count checkpoint-store rows referencing *thread_id* across real tables.

    Opens the worker-written checkpoint SQLite database read-only and sums the
    rows in every table that carries a ``thread_id`` column, so the assertion
    binds to the real persisted artifacts rather than to any one LangGraph table
    name. A read-only connection tolerates the gateway process holding the file.
    """
    checkpoint_path = derive_state_paths(app_home).checkpoint_path
    if not checkpoint_path.is_file():
        return 0
    uri = f"file:{checkpoint_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10.0) as connection:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        total = 0
        for table in tables:
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info('{table}')")
            }
            if "thread_id" not in columns:
                continue
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM '{table}' WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            total += int(count)
    return total


def test_deletion_removes_the_run_from_control_and_checkpoint_stores(
    gateway: CertifiedGateway,
) -> None:
    """S80: a completed run is deleted from both real stores and stays invisible.

    Discriminating across both stores: the run first exists (status 200,
    checkpoint rows present), then after one authenticated delete it is gone from
    the control store (status 404, product state 404, absent from active-run
    discovery) AND from the checkpoint store (zero rows for the run). A deletion
    that skipped the checkpoint store would leave a non-zero after-count and fail.
    """
    run_id = "run-deletion-cross-store"
    started = gateway.start(run_id)
    assert started.status_code == 201, started.text
    wait_for_terminal(gateway, run_id)

    # The run is durable in both stores before deletion.
    assert gateway.status(run_id).status_code == 200
    rows_before = _checkpoint_rows_for(gateway.app_home, run_id)
    assert rows_before > 0, "the run must genuinely checkpoint for a cross-store proof"

    deleted = gateway.delete_run(run_id)
    assert deleted.status_code == 204, deleted.text

    # Control store: invisible on every public read.
    assert gateway.status(run_id).status_code == 404
    assert gateway.thread_state(run_id).status_code == 404
    active = gateway.active_runs()
    assert active.status_code == 200
    assert all(record["run_id"] != run_id for record in active.json()["runs"])

    # Checkpoint store: the worker-written artifacts are gone.
    assert _checkpoint_rows_for(gateway.app_home, run_id) == 0


def test_replayed_delete_converges_without_a_second_teardown(
    gateway: CertifiedGateway,
) -> None:
    """S80: replaying a delete after completion converges rather than erroring.

    Discriminating: the first delete of a real run succeeds (204) and the run is
    gone, and a second identical delete returns a clean 404 - the converged
    outcome - rather than a 500 or a second teardown. Deleting a run that never
    existed also returns 404, so the replay's 404 is the not-present contract, not
    an error masquerading as success.
    """
    run_id = "run-deletion-replay"
    started = gateway.start(run_id)
    assert started.status_code == 201, started.text
    wait_for_terminal(gateway, run_id)

    first = gateway.delete_run(run_id)
    assert first.status_code == 204, first.text

    replay = gateway.delete_run(run_id)
    assert replay.status_code == 404, replay.text

    never_existed = gateway.delete_run("run-deletion-never-existed")
    assert never_existed.status_code == 404, never_existed.text
