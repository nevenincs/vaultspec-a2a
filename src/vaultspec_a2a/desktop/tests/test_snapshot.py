"""Real-store tests for the consistency-group snapshot and restore primitive.

Every test builds real SQLite databases with real content on disk and drives the
production snapshot and restore functions against them. No mock, monkeypatch,
stub, skip, or expected failure is used: capture is proved by reading the real
committed descriptor and captured copies, restore is proved by querying the real
restored rows, refusals are proved by holding a real SQLite write lock, and
interruption recovery is proved by constructing the real on-disk intermediate
states the code itself defines.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ..profile import derive_state_paths
from ..snapshot import (
    DESCRIPTOR_NAME,
    RESTORE_MARKER_NAME,
    ConsistencyGroupStore,
    RestorePendingError,
    SnapshotIntegrityError,
    SnapshotStoreLockedError,
    consistency_group_members,
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


def _seed_primary(path: Path, revision: str, marker: str) -> None:
    """Write a real Alembic-style primary store with distinguishable content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        conn.execute("CREATE TABLE threads (id INTEGER PRIMARY KEY, label TEXT)")
        conn.execute("INSERT INTO threads (label) VALUES (?)", (marker,))
        conn.commit()
    finally:
        conn.close()


def _seed_checkpoint(path: Path, marker: str, *, wal: bool = False) -> None:
    """Write a real checkpoint-style store; optionally leave content in the WAL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, state TEXT)")
        conn.execute("INSERT INTO checkpoints (state) VALUES (?)", (marker,))
        conn.commit()
    finally:
        conn.close()


def _read_label(path: Path, table: str, column: str) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return str(conn.execute(f"SELECT {column} FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _seed_group(home: Path, *, primary_marker: str, checkpoint_marker: str) -> None:
    state = derive_state_paths(home)
    _seed_primary(state.database_path, "rev-head", primary_marker)
    _seed_checkpoint(state.checkpoint_path, checkpoint_marker)


class TestSnapshotCapture:
    def test_captures_both_members_and_commits_descriptor(self, tmp_path: Path) -> None:
        """A snapshot captures every member and commits one atomic descriptor."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p-original", checkpoint_marker="c-original")

        descriptor = create_snapshot(home, "grp-1")

        assert descriptor.group_id == "grp-1"
        assert {s.store for s in descriptor.stores} == set(ConsistencyGroupStore)
        state = derive_state_paths(home)
        assert descriptor_path(state, "grp-1").is_file()
        primary = next(
            s for s in descriptor.stores if s.store is ConsistencyGroupStore.PRIMARY
        )
        assert primary.alembic_revision == "rev-head"
        assert primary.size_bytes > 0
        # The committed capture is inspectable and digest-consistent.
        assert inspect_snapshot(home, "grp-1").group_id == "grp-1"
        assert list_snapshots(home) == ("grp-1",)

    def test_capture_leaves_source_committed_content_intact(
        self, tmp_path: Path
    ) -> None:
        """Capturing a store reads it without altering its committed rows."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p-keep", checkpoint_marker="c-keep")
        state = derive_state_paths(home)

        create_snapshot(home, "grp-keep")

        assert _read_label(state.database_path, "threads", "label") == "p-keep"
        assert _read_label(state.checkpoint_path, "checkpoints", "state") == "c-keep"

    def test_wal_resident_content_is_captured_coherently(self, tmp_path: Path) -> None:
        """Committed content still living in the WAL is captured by the backup."""
        home = tmp_path / "app"
        state = derive_state_paths(home)
        _seed_primary(state.database_path, "rev-head", "p-wal")
        _seed_checkpoint(state.checkpoint_path, "c-wal", wal=True)

        create_snapshot(home, "grp-wal")
        # Mutate the live checkpoint, then restore and prove the WAL-era row returned.
        conn = sqlite3.connect(str(state.checkpoint_path))
        try:
            conn.execute("UPDATE checkpoints SET state='c-changed'")
            conn.commit()
        finally:
            conn.close()

        restore_snapshot(home, "grp-wal")
        assert _read_label(state.checkpoint_path, "checkpoints", "state") == "c-wal"

    def test_missing_member_is_an_integrity_failure(self, tmp_path: Path) -> None:
        """A non-derivable member that is absent fails the whole capture closed."""
        home = tmp_path / "app"
        state = derive_state_paths(home)
        _seed_primary(state.database_path, "rev-head", "p-only")
        # Checkpoint store deliberately absent.

        with pytest.raises(SnapshotIntegrityError):
            create_snapshot(home, "grp-missing")

    def test_live_store_capture_is_refused(self, tmp_path: Path) -> None:
        """A member held under a real write lock refuses capture."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p", checkpoint_marker="c")
        state = derive_state_paths(home)

        holder = sqlite3.connect(str(state.database_path))
        try:
            holder.execute("BEGIN IMMEDIATE")
            with pytest.raises(SnapshotStoreLockedError):
                create_snapshot(home, "grp-live")
        finally:
            holder.rollback()
            holder.close()

    def test_duplicate_group_id_is_refused(self, tmp_path: Path) -> None:
        """A committed group id cannot be recommitted."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p", checkpoint_marker="c")
        create_snapshot(home, "grp-dup")

        with pytest.raises(Exception, match="already committed"):
            create_snapshot(home, "grp-dup")


class TestSnapshotVisibility:
    def test_uncommitted_group_is_invisible(self, tmp_path: Path) -> None:
        """A group directory without a committed descriptor is not reported."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p", checkpoint_marker="c")
        state = derive_state_paths(home)
        # Construct the real "captured, not yet committed" on-disk state.
        stage = state.snapshots_dir / "grp-staged"
        stage.mkdir(parents=True)
        (stage / "primary.db").write_bytes(b"partial")

        assert list_snapshots(home) == ()
        with pytest.raises(SnapshotIntegrityError):
            inspect_snapshot(home, "grp-staged")

    def test_tampered_capture_fails_inspection(self, tmp_path: Path) -> None:
        """A captured store whose bytes changed post-commit fails inspection."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p", checkpoint_marker="c")
        create_snapshot(home, "grp-tamper")
        state = derive_state_paths(home)
        (state.snapshots_dir / "grp-tamper" / "primary.db").write_bytes(b"tampered")

        with pytest.raises(SnapshotIntegrityError):
            inspect_snapshot(home, "grp-tamper")


class TestRestore:
    def test_restore_returns_both_stores_to_snapshot_content(
        self, tmp_path: Path
    ) -> None:
        """Mutating both stores then restoring returns both to the snapshot."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p-snap", checkpoint_marker="c-snap")
        state = derive_state_paths(home)
        create_snapshot(home, "grp-r")

        for path, table in (
            (state.database_path, "threads"),
            (state.checkpoint_path, "checkpoints"),
        ):
            conn = sqlite3.connect(str(path))
            try:
                column = "label" if table == "threads" else "state"
                conn.execute(f"UPDATE {table} SET {column}='mutated'")
                conn.commit()
            finally:
                conn.close()

        outcome = restore_snapshot(home, "grp-r")

        assert set(outcome.restored) == set(ConsistencyGroupStore)
        assert outcome.resumed is False
        assert _read_label(state.database_path, "threads", "label") == "p-snap"
        assert _read_label(state.checkpoint_path, "checkpoints", "state") == "c-snap"
        assert pending_restore(home) is None

    def test_restore_refuses_live_store(self, tmp_path: Path) -> None:
        """A live target store refuses restore before the marker is written."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p", checkpoint_marker="c")
        state = derive_state_paths(home)
        create_snapshot(home, "grp-rl")

        holder = sqlite3.connect(str(state.checkpoint_path))
        try:
            holder.execute("BEGIN IMMEDIATE")
            with pytest.raises(SnapshotStoreLockedError):
                restore_snapshot(home, "grp-rl")
        finally:
            holder.rollback()
            holder.close()
        assert pending_restore(home) is None

    def test_restore_of_uncommitted_group_is_refused(self, tmp_path: Path) -> None:
        """Restoring a group with no committed descriptor fails closed."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p", checkpoint_marker="c")

        with pytest.raises(SnapshotIntegrityError):
            restore_snapshot(home, "never-captured")


class TestInterruptedRestore:
    def test_pending_marker_blocks_fresh_restore(self, tmp_path: Path) -> None:
        """A leftover restore marker refuses a fresh restore and is detectable."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p-snap", checkpoint_marker="c-snap")
        state = derive_state_paths(home)
        create_snapshot(home, "grp-i")

        # Construct the real "marker written, restore interrupted" on-disk state
        # by writing the marker exactly as the production path would.
        marker = restore_marker_path(state)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            (
                '{"marker_version":"1","group_id":"grp-i","app_home":'
                f'"{state.app_home.as_posix()}","started_at":'
                f'"{datetime.now(UTC).isoformat()}",'
                '"stores":["primary","checkpoint"]}'
            ),
            encoding="utf-8",
        )

        marker_model = pending_restore(home)
        assert marker_model is not None
        assert marker_model.group_id == "grp-i"
        with pytest.raises(RestorePendingError):
            restore_snapshot(home, "grp-i")

    def test_resume_rolls_forward_and_clears_marker(self, tmp_path: Path) -> None:
        """Resuming an interrupted restore converges the group and clears the marker."""
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p-snap", checkpoint_marker="c-snap")
        state = derive_state_paths(home)
        create_snapshot(home, "grp-i2")

        # Mutate both stores and leave a marker: the real half-way interruption.
        for path, table, column in (
            (state.database_path, "threads", "label"),
            (state.checkpoint_path, "checkpoints", "state"),
        ):
            conn = sqlite3.connect(str(path))
            try:
                conn.execute(f"UPDATE {table} SET {column}='mid-restore'")
                conn.commit()
            finally:
                conn.close()
        marker = restore_marker_path(state)
        marker.write_text(
            (
                '{"marker_version":"1","group_id":"grp-i2","app_home":'
                f'"{state.app_home.as_posix()}","started_at":'
                f'"{datetime.now(UTC).isoformat()}",'
                '"stores":["primary","checkpoint"]}'
            ),
            encoding="utf-8",
        )

        outcome = restore_snapshot(home, "grp-i2", resume=True)

        assert outcome.resumed is True
        assert _read_label(state.database_path, "threads", "label") == "p-snap"
        assert _read_label(state.checkpoint_path, "checkpoints", "state") == "c-snap"
        assert pending_restore(home) is None
        assert not (state.snapshots_dir / RESTORE_MARKER_NAME).exists()

    def test_resume_of_mismatched_group_is_refused(self, tmp_path: Path) -> None:
        """Resuming a different group than the pending marker is refused.

        A mismatched resume would silently overwrite the pending marker and
        abandon the interrupted group half-applied, so it fails closed.
        """
        home = tmp_path / "app"
        _seed_group(home, primary_marker="p-snap", checkpoint_marker="c-snap")
        state = derive_state_paths(home)
        create_snapshot(home, "grp-pending")
        create_snapshot(home, "grp-other")

        # An interrupted restore of grp-pending is on disk.
        marker = restore_marker_path(state)
        marker.write_text(
            (
                '{"marker_version":"1","group_id":"grp-pending","app_home":'
                f'"{state.app_home.as_posix()}","started_at":'
                f'"{datetime.now(UTC).isoformat()}",'
                '"stores":["primary","checkpoint"]}'
            ),
            encoding="utf-8",
        )

        # Resuming a DIFFERENT group must not proceed and must not clear the marker.
        with pytest.raises(RestorePendingError, match="different group"):
            restore_snapshot(home, "grp-other", resume=True)
        still_pending = pending_restore(home)
        assert still_pending is not None
        assert still_pending.group_id == "grp-pending"


def test_membership_is_both_non_derivable_stores(tmp_path: Path) -> None:
    """The declared group is exactly the primary and checkpoint, both mandatory."""
    state = derive_state_paths(tmp_path / "app")
    members = consistency_group_members(state)

    assert tuple(m.store for m in members) == (
        ConsistencyGroupStore.PRIMARY,
        ConsistencyGroupStore.CHECKPOINT,
    )
    assert all(not m.derivable for m in members)
    assert {m.snapshot_filename for m in members} == {"primary.db", "checkpoint.db"}
    _ = DESCRIPTOR_NAME  # descriptor filename is part of the public contract
