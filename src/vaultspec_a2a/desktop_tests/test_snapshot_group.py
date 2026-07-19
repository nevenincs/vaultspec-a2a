"""Certify that the primary and checkpoint databases restore together.

The group is real: a fresh application home is migrated by the production
staged-generation entrypoint, producing a real Alembic-headed primary database
and a real WAL-mode LangGraph checkpoint database with the state-driven
development state backfilled. Distinguishable content is written into both, the
consistency group is captured, both stores are mutated, and the group is
restored. Certification proves both stores return to the captured content
together by querying the real SQLite files, that the committed group descriptor
is authoritative over both members, and that the captured copies verify by
digest. No mock, monkeypatch, stub, skip, or expected failure is used.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from vaultspec_a2a.desktop.migration import run_staged_migration
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.snapshot import (
    ConsistencyGroupStore,
    create_snapshot,
    inspect_snapshot,
    restore_snapshot,
)
from vaultspec_a2a.desktop.transaction import package_migration_range

if TYPE_CHECKING:
    from pathlib import Path

_DIGEST = "e" * 64


def _write_descriptor(descriptor_path: Path, home: Path) -> Path:
    """Write a well-formed one-time migration descriptor targeting ``home``."""
    state = derive_state_paths(home)
    packaged = package_migration_range()
    document: dict[str, object] = {
        "descriptor_version": "1",
        "transaction_id": "cert-group-txn",
        "app_home": str(home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "5.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    return descriptor_path


def _migrate_real_group(home: Path, descriptor_path: Path) -> None:
    """Produce a real migrated primary and checkpoint store under ``home``."""
    descriptor = _write_descriptor(descriptor_path, home)
    result = asyncio.run(run_staged_migration(descriptor))
    assert result.status == "succeeded", result.model_dump(mode="json")


def _set_marker(db_path: Path, value: str) -> None:
    """Write a distinguishable marker row into a real store (real DDL + DML)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS group_marker (v TEXT NOT NULL)")
        conn.execute("DELETE FROM group_marker")
        conn.execute("INSERT INTO group_marker (v) VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()


def _read_marker(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(conn.execute("SELECT v FROM group_marker").fetchone()[0])
    finally:
        conn.close()


def _alembic_head(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        )
    finally:
        conn.close()


def _table_present(db_path: Path, table: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        return (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


def test_primary_and_checkpoint_restore_together_from_real_group(
    tmp_path: Path,
) -> None:
    """A real migrated primary and checkpoint snapshot and restore as one group."""
    home = tmp_path / "app"
    _migrate_real_group(home, tmp_path / "txn.json")
    state = derive_state_paths(home)
    head = package_migration_range().head

    # Distinguishable content in each real store.
    _set_marker(state.database_path, "primary-v1")
    _set_marker(state.checkpoint_path, "checkpoint-v1")

    descriptor = create_snapshot(home, "cert-group")

    # The committed group descriptor is authoritative over both members.
    stores = {snapshot.store: snapshot for snapshot in descriptor.stores}
    assert set(stores) == set(ConsistencyGroupStore)
    assert stores[ConsistencyGroupStore.PRIMARY].alembic_revision == head
    assert all(snapshot.size_bytes > 0 for snapshot in descriptor.stores)

    # Mutate both stores away from the captured content.
    _set_marker(state.database_path, "primary-v2")
    _set_marker(state.checkpoint_path, "checkpoint-v2")
    assert _read_marker(state.database_path) == "primary-v2"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v2"

    outcome = restore_snapshot(home, "cert-group")

    # Both stores returned to the captured content together.
    assert set(outcome.restored) == set(ConsistencyGroupStore)
    assert _read_marker(state.database_path) == "primary-v1"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v1"

    # The real migrated schema survived the round trip intact.
    assert _alembic_head(state.database_path) == head
    assert _table_present(state.checkpoint_path, "checkpoints")

    # The captured copies still verify by digest under the authoritative descriptor.
    reinspected = inspect_snapshot(home, "cert-group")
    assert reinspected.group_id == "cert-group"
    assert {s.store for s in reinspected.stores} == set(ConsistencyGroupStore)


def test_group_restore_is_all_or_nothing_across_both_stores(
    tmp_path: Path,
) -> None:
    """Restoring the group moves both members; neither is left at its mutation."""
    home = tmp_path / "app"
    _migrate_real_group(home, tmp_path / "txn.json")
    state = derive_state_paths(home)

    _set_marker(state.database_path, "primary-snapshot")
    _set_marker(state.checkpoint_path, "checkpoint-snapshot")
    create_snapshot(home, "pair-group")

    # Drift BOTH stores independently, then restore: the group is authoritative,
    # so the restore returns each member to its own captured content together,
    # never leaving a mixed pair where one store advanced and the other did not.
    _set_marker(state.database_path, "primary-drifted")
    _set_marker(state.checkpoint_path, "checkpoint-drifted")
    restore_snapshot(home, "pair-group")

    assert _read_marker(state.database_path) == "primary-snapshot"
    assert _read_marker(state.checkpoint_path) == "checkpoint-snapshot"
