"""Tests for the snapshot replay verdict in control/projection.py."""

from __future__ import annotations

from ...thread.enums import DegradedReason, RepairStatus, ThreadStatus
from ...thread.snapshots import ThreadStateSnapshot
from ..projection import finalize_snapshot_replay_status

# ---------------------------------------------------------------------------
# finalize_snapshot_replay_status
# ---------------------------------------------------------------------------


def test_finalize_durable() -> None:
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0
    )
    result = finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=True,
        checkpoint_present=True,
        checkpoint_error=False,
        thread_status="running",
    )
    assert result.replay_status == "durable"


def test_finalize_checkpoint_error() -> None:
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0
    )
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=True,
        thread_status="running",
    )
    assert snap.replay_status == "unknown"
    assert snap.snapshot_complete is False


def test_finalize_best_effort() -> None:
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0
    )
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=True,
        checkpoint_error=False,
        thread_status="running",
    )
    assert snap.replay_status == "best_effort"
    assert snap.snapshot_complete is False


def test_finalize_submitted_no_checkpoint() -> None:
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.SUBMITTED, last_sequence=0
    )
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="submitted",
    )
    assert snap.replay_status == "unknown"
    assert snap.snapshot_complete is True


def test_finalize_gap_detected() -> None:
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0
    )
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="running",
    )
    assert snap.replay_status == "gap_detected"
    assert "checkpoint_missing" in snap.degraded_reasons
    # A detected replay gap classifies as a replay gap. The probe succeeded and
    # found no checkpoint, so the missing history is established rather than
    # unknown - reporting it as checkpoint-unavailable claimed the opposite, and
    # left RepairStatus.REPLAY_GAP with no producer anywhere in the codebase.
    assert snap.repair_status == RepairStatus.REPLAY_GAP.value
    assert snap.execution_readiness == RepairStatus.REPLAY_GAP.value


def test_replay_gap_is_distinct_from_checkpoint_unavailable() -> None:
    """The two checkpoint conditions do not collapse onto one classification.

    An unavailable checkpoint means the probe failed and the contents are
    unknown; a missing one means the probe succeeded and the history is provably
    absent. They are different operator situations, so the replay contract
    names a replay gap only for the second and leaves the first to the reader
    that knows why its probe failed.
    """
    missing = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0
    )
    finalize_snapshot_replay_status(
        missing,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="running",
    )
    unread = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.RUNNING, last_sequence=0
    )
    finalize_snapshot_replay_status(
        unread,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=True,
        thread_status="running",
    )

    assert missing.repair_status == RepairStatus.REPLAY_GAP.value
    assert DegradedReason.CHECKPOINT_MISSING in missing.degraded_reasons
    assert unread.repair_status is None
    assert DegradedReason.CHECKPOINT_MISSING not in unread.degraded_reasons
