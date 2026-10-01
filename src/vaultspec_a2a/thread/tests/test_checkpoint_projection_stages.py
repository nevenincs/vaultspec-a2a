"""The two projection stages must read - and be provable - apart.

``project_checkpoint_tuple`` was one 95-line function doing two jobs: extracting
the checkpoint's own immutable fields, then folding the pending-write and
interrupt view onto them. Split, each stage is now assertable on its own, which
the combined function never allowed.

Real ``CheckpointTuple`` objects throughout, matching the existing projection
suite - no stand-ins for the type under projection.
"""

from __future__ import annotations

import operator
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict, cast

import pytest
from langgraph.checkpoint.base import CheckpointTuple, PendingWrite
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Interrupt, interrupt

from ..snapshots import (
    extract_checkpoint_fields,
    fold_pending_writes,
    project_checkpoint_tuple,
)
from ._graph_helpers import add_node, compile_graph


def _tuple(*, pending: list[PendingWrite] | None = None) -> CheckpointTuple:
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
    projection = extract_checkpoint_fields(_tuple(), thread_id="t-1", history_depth=2)

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
    projection = extract_checkpoint_fields(_tuple(), thread_id="t-1", history_depth=1)

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
    projection = extract_checkpoint_fields(
        tuple_with_interrupt, thread_id="t-1", history_depth=2
    )

    fold_pending_writes(projection, tuple_with_interrupt, thread_id="t-1")

    assert projection.pending_write_count == 1
    assert projection.pending_write_channels == ["__interrupt__"]
    assert projection.pause_cause == "plan_approval_request"
    assert projection.pending_interrupts[0].interrupt_id == "i-1"


def test_folding_marks_unknown_history_as_degraded() -> None:
    """A projection with no history depth records that as a degraded reason."""
    tup = _tuple()
    projection = extract_checkpoint_fields(tup, thread_id="t-1", history_depth=None)

    fold_pending_writes(projection, tup, thread_id="t-1")

    assert "checkpoint_history_unknown" in projection.degraded_reasons


def test_folding_flags_an_untyped_interrupt_payload() -> None:
    """A malformed interrupt surfaces a degraded reason, not a crash."""
    tup = _tuple(
        pending=[("task-1", "__interrupt__", [Interrupt(value={"no": "type"}, id="x")])]
    )
    projection = extract_checkpoint_fields(tup, thread_id="t-1", history_depth=1)

    fold_pending_writes(projection, tup, thread_id="t-1")

    assert "interrupt_payload_untyped" in projection.degraded_reasons
    assert projection.pending_interrupts == []


class _FanOutState(TypedDict, total=False):
    answers: Annotated[list[str], operator.add]


def _fan_out_graph(saver: InMemorySaver) -> Any:
    """Two branches that each stop to ask their own question."""

    def gate(request_id: str) -> Any:
        def node(state: _FanOutState) -> _FanOutState:
            del state
            answer = interrupt(
                {"type": "plan_approval_request", "request_id": request_id}
            )
            return {"answers": [f"{request_id}:{answer}"]}

        return node

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _FanOutState))
    add_node(builder, "alpha", gate("request-alpha"))
    add_node(builder, "beta", gate("request-beta"))
    builder.add_edge(START, "alpha")
    builder.add_edge(START, "beta")
    builder.add_edge("alpha", END)
    builder.add_edge("beta", END)
    return compile_graph(builder, checkpointer=saver)


@pytest.mark.asyncio
async def test_an_answered_branch_is_no_longer_a_question_the_run_discloses() -> None:
    """A reload must re-render the open questions, not the answered ones.

    This projection is what a client reads the run's pending permissions and
    parked clarification from. With work fanned out, the superstep holding
    both questions cannot commit while one branch is still parked, so the
    answered branch's interrupt write stays in the checkpoint and was
    disclosed alongside the live one on every reload.

    A real fan-out over a real saver, because the thing being read is exactly
    what LangGraph leaves in the store and a hand-built write set would only
    restate the assumption under test.
    """
    saver = InMemorySaver()
    graph = _fan_out_graph(saver)
    config: Any = {"configurable": {"thread_id": "fan-out-projection"}}

    await graph.ainvoke({"answers": []}, config)
    both = project_checkpoint_tuple(
        await saver.aget_tuple(config), thread_id="fan-out-projection"
    )
    assert {parked.interrupt_id for parked in both.pending_interrupts} == {
        "request-alpha",
        "request-beta",
    }

    answered = next(
        parked
        for parked in (await graph.aget_state(config)).interrupts
        if parked.value["request_id"] == "request-alpha"
    )
    await graph.ainvoke(Command(resume={answered.id: "approved"}), config)

    stored = await saver.aget_tuple(config)
    assert stored is not None
    remaining = project_checkpoint_tuple(stored, thread_id="fan-out-projection")

    assert [parked.interrupt_id for parked in remaining.pending_interrupts] == [
        "request-beta"
    ]
    assert remaining.pause_cause == "plan_approval_request"
    # The held writes themselves are still reported whole: they describe the
    # checkpoint, and only the questions were narrowed.
    assert remaining.pending_write_count == len(stored.pending_writes or [])
    assert "__interrupt__" in remaining.pending_write_channels


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

    staged = extract_checkpoint_fields(tup, thread_id="t-1", history_depth=4)
    fold_pending_writes(staged, tup, thread_id="t-1")

    assert combined == staged
