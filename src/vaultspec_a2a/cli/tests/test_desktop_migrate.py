"""Tests for the internal desktop migrate command on the operator CLI.

The command is driven as a real child process (the repo convention for CLI
coverage) against real on-disk descriptor files and real SQLite stores. No mock,
monkeypatch, stub, skip, or expected failure is used: success and failure are
proved by the real JSON result the command prints and by the real migrated
schema, and the run-control API surface is inspected to prove the lifecycle verb
is never exposed over HTTP.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ...desktop.profile import derive_state_paths
from ...desktop.transaction import package_migration_range

if TYPE_CHECKING:
    from pathlib import Path

_MODULE = "vaultspec_a2a.cli.main"
_DIGEST = "c" * 64


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the operator CLI as a real child process."""
    return subprocess.run(
        [sys.executable, "-m", _MODULE, *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _write_descriptor(descriptor_path: Path, home: Path, **overrides: object) -> Path:
    state = derive_state_paths(home)
    packaged = package_migration_range()
    document: dict[str, object] = {
        "descriptor_version": "1",
        "transaction_id": "cli-txn-1",
        "app_home": str(home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "3.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    document.update(overrides)
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    return descriptor_path


def test_cli_desktop_migrate_succeeds_and_prints_result(tmp_path: Path) -> None:
    """The real command migrates a fresh store and prints a success result."""
    home = tmp_path / "app"
    descriptor = _write_descriptor(tmp_path / "txn.json", home)
    state = derive_state_paths(home)
    packaged = package_migration_range()

    result = _run_cli("desktop-migrate", "--descriptor", str(descriptor))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "succeeded"
    assert payload["target_head"] == packaged.head
    assert payload["transaction_id"] == "cli-txn-1"
    stores = {store["store"]: store for store in payload["stores"]}
    assert stores["primary"]["status"] == "migrated"
    assert stores["primary"]["to_revision"] == packaged.head
    assert stores["checkpoint"]["status"] == "initialized"
    assert stores["sdd"]["status"] == "backfilled"

    version = (
        sqlite3.connect(str(state.database_path))
        .execute("SELECT version_num FROM alembic_version")
        .fetchone()
    )
    assert version is not None
    assert version[0] == packaged.head


def test_cli_desktop_migrate_reports_failure_and_exits_nonzero(
    tmp_path: Path,
) -> None:
    """A mismatched descriptor makes the command print failure and exit non-zero."""
    home = tmp_path / "app"
    descriptor = _write_descriptor(
        tmp_path / "txn.json",
        home,
        migration_range={"base": "0001", "head": "9999_future"},
    )

    result = _run_cli("desktop-migrate", "--descriptor", str(descriptor))

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "descriptor"
    assert payload["error_class"] == "TransactionDescriptorError"


def test_cli_desktop_migrate_requires_descriptor() -> None:
    """The command fails as a usage error when no descriptor is supplied."""
    result = _run_cli("desktop-migrate")
    assert result.returncode != 0
    assert "descriptor" in (result.stdout + result.stderr).lower()


def test_migrate_is_not_exposed_on_the_run_control_api() -> None:
    """No HTTP run-control route carries the desktop migration lifecycle verb."""
    from vaultspec_a2a.api.app import create_app
    from vaultspec_a2a.api.routes.gateway import route_signature

    signatures = route_signature(create_app())
    assert all("migrate" not in signature.lower() for signature in signatures)
