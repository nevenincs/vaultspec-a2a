"""Tests for the internal desktop snapshot commands on the operator CLI.

The commands are driven as real child processes (the repo convention for CLI
coverage) against real on-disk SQLite stores. No mock, monkeypatch, stub, skip,
or expected failure is used: capture, inspection, and restore are proved by the
real JSON the commands print and by querying the real restored SQLite rows;
refusals are proved by holding a real SQLite write lock; and the run-control API
surface is inspected to prove these lifecycle verbs are never exposed over HTTP.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from typing import TYPE_CHECKING

from ...desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from pathlib import Path

_MODULE = "vaultspec_a2a.cli.main"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the operator CLI as a real child process."""
    return subprocess.run(
        [sys.executable, "-m", _MODULE, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _seed_group(home: Path, *, primary: str, checkpoint: str) -> None:
    """Write real primary and checkpoint stores with distinguishable content."""
    state = derive_state_paths(home)
    state.database_path.parent.mkdir(parents=True, exist_ok=True)
    primary_conn = sqlite3.connect(str(state.database_path))
    try:
        primary_conn.execute(
            "CREATE TABLE threads (id INTEGER PRIMARY KEY, label TEXT)"
        )
        primary_conn.execute("INSERT INTO threads (label) VALUES (?)", (primary,))
        primary_conn.commit()
    finally:
        primary_conn.close()
    checkpoint_conn = sqlite3.connect(str(state.checkpoint_path))
    try:
        checkpoint_conn.execute(
            "CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, state TEXT)"
        )
        checkpoint_conn.execute(
            "INSERT INTO checkpoints (state) VALUES (?)", (checkpoint,)
        )
        checkpoint_conn.commit()
    finally:
        checkpoint_conn.close()


def _label(path: Path, table: str, column: str) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return str(conn.execute(f"SELECT {column} FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_cli_snapshot_create_inspect_and_restore_round_trip(tmp_path: Path) -> None:
    """Create commits a group, inspect reports it, restore returns both stores."""
    home = tmp_path / "app"
    _seed_group(home, primary="p-snap", checkpoint="c-snap")
    state = derive_state_paths(home)

    created = _run_cli(
        "desktop-snapshot-create", "--app-home", str(home), "--group-id", "grp-cli"
    )
    assert created.returncode == 0, created.stderr
    descriptor = json.loads(created.stdout)
    assert descriptor["group_id"] == "grp-cli"
    assert {store["store"] for store in descriptor["stores"]} == {
        "primary",
        "checkpoint",
    }

    inspected = _run_cli(
        "desktop-snapshot-inspect", "--app-home", str(home), "--group-id", "grp-cli"
    )
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["group_id"] == "grp-cli"

    # Mutate both stores, then restore from the committed group.
    for path, table, column in (
        (state.database_path, "threads", "label"),
        (state.checkpoint_path, "checkpoints", "state"),
    ):
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(f"UPDATE {table} SET {column}='mutated'")
            conn.commit()
        finally:
            conn.close()

    restored = _run_cli(
        "desktop-snapshot-restore", "--app-home", str(home), "--group-id", "grp-cli"
    )
    assert restored.returncode == 0, restored.stderr
    payload = json.loads(restored.stdout)
    assert payload["status"] == "succeeded"
    assert set(payload["restored"]) == {"primary", "checkpoint"}
    assert payload["resumed"] is False
    assert _label(state.database_path, "threads", "label") == "p-snap"
    assert _label(state.checkpoint_path, "checkpoints", "state") == "c-snap"


def test_cli_snapshot_inspect_uncommitted_group_fails(tmp_path: Path) -> None:
    """Inspecting a group that was never committed fails closed and exits non-zero."""
    home = tmp_path / "app"
    _seed_group(home, primary="p", checkpoint="c")

    result = _run_cli(
        "desktop-snapshot-inspect", "--app-home", str(home), "--group-id", "absent"
    )
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["operation"] == "inspect"
    assert payload["error_class"] == "SnapshotIntegrityError"


def test_cli_snapshot_restore_refuses_live_store(tmp_path: Path) -> None:
    """Restore requires quiescence: a live target store is refused, non-zero exit."""
    home = tmp_path / "app"
    _seed_group(home, primary="p-snap", checkpoint="c-snap")
    state = derive_state_paths(home)

    created = _run_cli(
        "desktop-snapshot-create", "--app-home", str(home), "--group-id", "grp-live"
    )
    assert created.returncode == 0, created.stderr

    holder = sqlite3.connect(str(state.checkpoint_path))
    try:
        holder.execute("BEGIN IMMEDIATE")
        result = _run_cli(
            "desktop-snapshot-restore",
            "--app-home",
            str(home),
            "--group-id",
            "grp-live",
        )
    finally:
        holder.rollback()
        holder.close()

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["operation"] == "restore"
    assert payload["error_class"] == "SnapshotStoreLockedError"


def test_cli_snapshot_create_requires_app_home_and_group_id() -> None:
    """The create command is a usage error when required options are missing."""
    result = _run_cli("desktop-snapshot-create")
    assert result.returncode != 0
    assert "app-home" in (result.stdout + result.stderr).lower()


def test_snapshot_verbs_are_not_exposed_on_the_run_control_api() -> None:
    """No HTTP run-control route carries a snapshot lifecycle verb."""
    from vaultspec_a2a.api.app import create_app
    from vaultspec_a2a.api.routes.gateway import route_signature

    signatures = route_signature(create_app())
    assert all("snapshot" not in signature.lower() for signature in signatures)
