"""Tests for the snapshot replay verdict in control/projection.py."""

from __future__ import annotations

import pytest

from ...thread.enums import (
    DegradedReason,
    RepairStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ...thread.snapshots import ThreadStateSnapshot, record_repair_posture
from ..projection import (
    classify_transcript_availability,
    finalize_snapshot_replay_status,
)

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
        thread_id="t1", status=ThreadStatus.INPUT_REQUIRED, last_sequence=0
    )
    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="input_required",
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
        thread_id="t1", status=ThreadStatus.INPUT_REQUIRED, last_sequence=0
    )
    finalize_snapshot_replay_status(
        missing,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="input_required",
    )
    unread = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.INPUT_REQUIRED, last_sequence=0
    )
    finalize_snapshot_replay_status(
        unread,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=True,
        thread_status="input_required",
    )

    assert missing.repair_status == RepairStatus.REPLAY_GAP.value
    assert DegradedReason.CHECKPOINT_MISSING in missing.degraded_reasons
    assert unread.repair_status is None
    assert DegradedReason.CHECKPOINT_MISSING not in unread.degraded_reasons


def test_a_graver_posture_survives_the_replay_gap() -> None:
    """A gap found late in a read cannot talk a run down from a worse posture.

    ``replay_gap`` is the mildest degraded posture, so overwriting with it let
    the final step of a read undo what an earlier step established: a run
    recorded as ``checkpoint_unavailable``, or found to need reconciliation,
    listed and read as a mere replay gap.
    """
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus.INPUT_REQUIRED, last_sequence=0
    )
    record_repair_posture(snap, RepairStatus.CHECKPOINT_UNAVAILABLE.value)

    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status="input_required",
    )

    assert snap.repair_status == RepairStatus.CHECKPOINT_UNAVAILABLE.value
    assert snap.execution_readiness == RepairStatus.CHECKPOINT_UNAVAILABLE.value
    # The gap is still reported: escalation withholds the posture, not the fact.
    assert snap.replay_status == "gap_detected"
    assert DegradedReason.CHECKPOINT_MISSING in snap.degraded_reasons


#: Every status a run can legitimately hold before its first checkpoint exists.
_PRE_CHECKPOINT = ["submitted", "running", "cancelling"]

#: Statuses a run reaches only after it has been checkpointed at least once.
_OWES_TRANSCRIPT = ["input_required", "completed", "failed", "repair_needed"]


@pytest.mark.parametrize("status", _PRE_CHECKPOINT)
def test_both_verdicts_excuse_a_run_before_its_first_checkpoint(status: str) -> None:
    """The replay verdict and the transcript verdict excuse the same window.

    A run is marked running the moment it dispatches, well before the worker
    writes anything, and it can be cancelled inside that window. Both verdicts
    answer from the same four facts, so a window one of them calls normal
    startup and the other calls a lost record is a disagreement about one run.
    """
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus(status), last_sequence=0
    )

    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status=status,
    )

    assert snap.replay_status == "unknown"
    assert snap.snapshot_complete is True
    assert DegradedReason.CHECKPOINT_MISSING not in snap.degraded_reasons
    assert snap.repair_status is None
    assert (
        classify_transcript_availability(
            checkpoint_loaded=False,
            checkpoint_present=False,
            checkpoint_error=False,
            thread_status=status,
        )
        is TranscriptAvailability.NOT_YET_RECORDED
    )


@pytest.mark.parametrize("status", _OWES_TRANSCRIPT)
def test_both_verdicts_report_a_run_that_owes_a_transcript(status: str) -> None:
    """The other half of the agreement: neither verdict excuses a real loss."""
    snap = ThreadStateSnapshot(
        thread_id="t1", status=ThreadStatus(status), last_sequence=0
    )

    finalize_snapshot_replay_status(
        snap,
        checkpoint_loaded=False,
        checkpoint_present=False,
        checkpoint_error=False,
        thread_status=status,
    )

    assert snap.replay_status == "gap_detected"
    assert snap.snapshot_complete is False
    assert DegradedReason.CHECKPOINT_MISSING in snap.degraded_reasons
    assert snap.repair_status == RepairStatus.REPLAY_GAP.value
    assert (
        classify_transcript_availability(
            checkpoint_loaded=False,
            checkpoint_present=False,
            checkpoint_error=False,
            thread_status=status,
        )
        is TranscriptAvailability.MISSING
    )
