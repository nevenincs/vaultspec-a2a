"""The two projection stages must read - and be provable - apart.

``project_checkpoint_tuple`` was one 95-line function doing two jobs: extracting
the checkpoint's own immutable fields, then folding the pending-write and
interrupt view onto them. Split, each stage is now assertable on its own, which
the combined function never allowed.

Real ``CheckpointTuple`` objects throughout, matching the existing projection
suite - no stand-ins for the type under projection.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langgraph.checkpoint.base import CheckpointTuple
from langgraph.types import Interrupt

from ..snapshots import (
    _extract_checkpoint_fields,
    _fold_pending_writes,
    project_checkpoint_tuple,
)


def _tuple(*, pending: list | None = None) -> CheckpointTuple:
    return CheckpointTuple(
        config={"configurable": {"thread_id": "t-1", "checkpoint_id": "cp-1"}},
        checkpoint={
            "v": 1,
            "id": "cp-1",
            "ts": "2026-03-09T10:20:49.387246+00:00",
            "channel_values": {"plan": [{"content": "x"}]},
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": ["plan"],
        },
        metadata={"source": "loop", "step": 3, "parents": {}},
        pending_writes=pending or [],
    )


def test_extraction_reads_only_the_checkpoints_own_fields() -> None:
    """The extraction stage produces the immutable description, no pending view."""
    projection = _extract_checkpoint_fields(_tuple(), thread_id="t-1", history_depth=2)

    assert projection.checkpoint_id == "cp-1"
    assert projection.checkpoint_source == "loop"
    assert projection.checkpoint_step == 3
    assert projection.checkpoint_updated_channels == ["plan"]
    assert projection.checkpoint_created_at == datetime(
        2026, 3, 9, 10, 20, 49, 387246, tzinfo=UTC
    )
    # The pending view is untouched by extraction alone.
    assert projection.pending_write_count == 0
    assert projection.pending_interrupts == []
    assert projection.pause_cause is None


def test_extraction_stamps_the_checkpoint_id_into_the_resumable_config() -> None:
    """A resumable config must name the checkpoint the caller can resume from."""
    projection = _extract_checkpoint_fields(_tuple(), thread_id="t-1", history_depth=1)

    assert projection.config["configurable"]["checkpoint_id"] == "cp-1"


def test_folding_adds_the_pending_interrupt_view_onto_a_base_projection() -> None:
    """The fold stage layers pending writes and interrupts onto extraction output."""
    tuple_with_interrupt = _tuple(
        pending=[
            (
                "task-1",
                "__interrupt__",
                [Interrupt(value={"type": "plan_approval_request"}, id="i-1")],
            )
        ]
    )
    projection = _extract_checkpoint_fields(
        tuple_with_interrupt, thread_id="t-1", history_depth=2
    )

    _fold_pending_writes(projection, tuple_with_interrupt, thread_id="t-1")

    assert projection.pending_write_count == 1
    assert projection.pending_write_channels == ["__interrupt__"]
    assert projection.pause_cause == "plan_approval_request"
    assert projection.pending_interrupts[0].interrupt_id == "i-1"


def test_folding_marks_unknown_history_as_degraded() -> None:
    """A projection with no history depth records that as a degraded reason."""
    tup = _tuple()
    projection = _extract_checkpoint_fields(tup, thread_id="t-1", history_depth=None)

    _fold_pending_writes(projection, tup, thread_id="t-1")

    assert "checkpoint_history_unknown" in projection.degraded_reasons


def test_folding_flags_an_untyped_interrupt_payload() -> None:
    """A malformed interrupt surfaces a degraded reason, not a crash."""
    tup = _tuple(
        pending=[("task-1", "__interrupt__", [Interrupt(value={"no": "type"}, id="x")])]
    )
    projection = _extract_checkpoint_fields(tup, thread_id="t-1", history_depth=1)

    _fold_pending_writes(projection, tup, thread_id="t-1")

    assert "interrupt_payload_untyped" in projection.degraded_reasons
    assert projection.pending_interrupts == []


def test_the_composed_function_equals_the_two_stages_run_in_order() -> None:
    """The public function must be exactly extraction followed by folding."""
    tup = _tuple(
        pending=[
            (
                "task-1",
                "__interrupt__",
                [Interrupt(value={"type": "plan_approval_request"}, id="i-9")],
            )
        ]
    )

    combined = project_checkpoint_tuple(tup, thread_id="t-1", history_depth=4)

    staged = _extract_checkpoint_fields(tup, thread_id="t-1", history_depth=4)
    _fold_pending_writes(staged, tup, thread_id="t-1")

    assert combined == staged
