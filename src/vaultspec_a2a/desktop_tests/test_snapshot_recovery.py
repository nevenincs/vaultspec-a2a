"""Certify that an interrupted snapshot or restore never exposes a half group.

The certification constructs, on real files, the exact intermediate on-disk
states an interruption leaves at each stage boundary the snapshot module defines,
and proves recovery is safe at every one:

- a snapshot interrupted after the captured stores are written but before the
  group descriptor commits is invisible to inspection;
- a restore interrupted after the quiesced marker is written but before the first
  store is restored is detected via the marker and refuses a fresh restore;
- a restore interrupted between the two stores -- a genuine half-restored pair on
  disk -- is never reported healthy and rolls forward to a consistent group;
- a restore interrupted after the last store but before the marker clears is
  still detected and converges idempotently.

Every state is built from a real captured group and real SQLite stores using the
module's own descriptor and marker layout. No mock, monkeypatch, stub, skip, or
expected failure is used.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.snapshot import (
    MARKER_VERSION,
    ConsistencyGroupStore,
    GroupDescriptor,
    RestoreMarker,
    RestorePendingError,
    SnapshotIntegrityError,
    create_snapshot,
    descriptor_path,
    inspect_snapshot,
    list_snapshots,
    pending_restore,
    restore_marker_path,
    restore_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path

_GROUP = "rec-group"


def _seed_store(path: Path, marker: str) -> None:
    """Create a real SQLite store with a distinguishable marker row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE group_marker (v TEXT NOT NULL)")
        conn.execute("INSERT INTO group_marker (v) VALUES (?)", (marker,))
        conn.commit()
    finally:
        conn.close()


def _set_marker(path: Path, marker: str) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("UPDATE group_marker SET v=?", (marker,))
        conn.commit()
    finally:
        conn.close()


def _read_marker(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return str(conn.execute("SELECT v FROM group_marker").fetchone()[0])
    finally:
        conn.close()


def _real_group(tmp_path: Path) -> tuple[Path, GroupDescriptor]:
    """Build a real captured consistency group and return (app_home, descriptor)."""
    home = tmp_path / "app"
    state = derive_state_paths(home)
    _seed_store(state.database_path, "primary-v1")
    _seed_store(state.checkpoint_path, "checkpoint-v1")
    descriptor = create_snapshot(home, _GROUP)
    return home, descriptor


def _write_marker(home: Path) -> None:
    """Write the quiesced-restore marker exactly as the production path would."""
    state = derive_state_paths(home)
    marker = RestoreMarker(
        marker_version=MARKER_VERSION,
        group_id=_GROUP,
        app_home=state.app_home,
        started_at=datetime.now(UTC),
        stores=(ConsistencyGroupStore.PRIMARY, ConsistencyGroupStore.CHECKPOINT),
    )
    path = restore_marker_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(marker.model_dump_json(), encoding="utf-8")


def _restore_one_store_from_capture(
    home: Path, descriptor: GroupDescriptor, store: ConsistencyGroupStore
) -> None:
    """Reproduce the on-disk effect of one completed per-store restore."""
    state = derive_state_paths(home)
    group_dir = descriptor_path(state, _GROUP).parent
    snapshot = next(s for s in descriptor.stores if s.store is store)
    shutil.copyfile(group_dir / snapshot.snapshot_filename, snapshot.source_path)


def test_uncommitted_snapshot_is_invisible_to_inspection(tmp_path: Path) -> None:
    """A capture interrupted before the descriptor commit is not a visible group."""
    home, _ = _real_group(tmp_path)
    state = derive_state_paths(home)

    # The real pre-commit crash state: captured stores present, descriptor absent.
    descriptor_path(state, _GROUP).unlink()

    assert _GROUP not in list_snapshots(home)
    with pytest.raises(SnapshotIntegrityError):
        inspect_snapshot(home, _GROUP)


def test_restore_interrupted_before_first_store_is_detected_and_recovers(
    tmp_path: Path,
) -> None:
    """A marker written before any store restore is detected and rolls forward."""
    home, _ = _real_group(tmp_path)
    state = derive_state_paths(home)
    _set_marker(state.database_path, "primary-v2")
    _set_marker(state.checkpoint_path, "checkpoint-v2")

    _write_marker(home)  # crash after marker, before first store

    detected = pending_restore(home)
    assert detected is not None and detected.group_id == _GROUP
    with pytest.raises(RestorePendingError):
        restore_snapshot(home, _GROUP)

    outcome = restore_snapshot(home, _GROUP, resume=True)
    assert outcome.resumed is True
    assert _read_marker(state.database_path) == "primary-v1"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v1"
    assert pending_restore(home) is None


def test_half_restored_pair_between_stores_is_never_healthy(tmp_path: Path) -> None:
    """A genuine half-restored pair is flagged not-healthy and converges on resume."""
    home, descriptor = _real_group(tmp_path)
    state = derive_state_paths(home)
    _set_marker(state.database_path, "primary-v2")
    _set_marker(state.checkpoint_path, "checkpoint-v2")

    # Crash between stores: primary restored, checkpoint still mutated, marker set.
    _restore_one_store_from_capture(home, descriptor, ConsistencyGroupStore.PRIMARY)
    _write_marker(home)
    assert _read_marker(state.database_path) == "primary-v1"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v2"

    # The half-restored pair is never healthy: the marker is the durable signal,
    # and a fresh restore is refused while it stands.
    assert pending_restore(home) is not None
    with pytest.raises(RestorePendingError):
        restore_snapshot(home, _GROUP)

    outcome = restore_snapshot(home, _GROUP, resume=True)
    assert outcome.resumed is True
    assert _read_marker(state.database_path) == "primary-v1"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v1"
    assert pending_restore(home) is None


def test_restore_interrupted_before_marker_clear_converges_idempotently(
    tmp_path: Path,
) -> None:
    """A marker surviving a fully-applied restore is detected and resumes cleanly."""
    home, descriptor = _real_group(tmp_path)
    state = derive_state_paths(home)

    # Crash after the last store restored but before the marker cleared: both
    # stores already hold the captured content, marker still present.
    _restore_one_store_from_capture(home, descriptor, ConsistencyGroupStore.PRIMARY)
    _restore_one_store_from_capture(home, descriptor, ConsistencyGroupStore.CHECKPOINT)
    _write_marker(home)

    assert pending_restore(home) is not None
    outcome = restore_snapshot(home, _GROUP, resume=True)
    assert outcome.resumed is True
    assert _read_marker(state.database_path) == "primary-v1"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v1"
    assert pending_restore(home) is None


def test_clean_round_trip_leaves_no_pending_restore(tmp_path: Path) -> None:
    """An uninterrupted snapshot and restore leaves the group healthy (no marker)."""
    home, _ = _real_group(tmp_path)
    state = derive_state_paths(home)
    _set_marker(state.database_path, "primary-v2")
    _set_marker(state.checkpoint_path, "checkpoint-v2")

    restore_snapshot(home, _GROUP)

    assert pending_restore(home) is None
    assert _read_marker(state.database_path) == "primary-v1"
    assert _read_marker(state.checkpoint_path) == "checkpoint-v1"
    # The committed group remains authoritative and digest-consistent.
    assert inspect_snapshot(home, _GROUP).group_id == _GROUP
