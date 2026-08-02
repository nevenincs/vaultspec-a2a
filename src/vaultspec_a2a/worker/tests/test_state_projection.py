"""State-normalization contract coverage for execution-state projection."""

from __future__ import annotations

from datetime import UTC, datetime

from langgraph.types import Interrupt, PregelTask
from pydantic import BaseModel, ConfigDict

from ..state_projection import StateProjector


class _StateNormalizationFixture(BaseModel):
    """Typed fixture for the normalizer's explicit snapshot field contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    next: tuple[str, ...]
    interrupts: tuple[Interrupt, ...]
    tasks: tuple[PregelTask, ...]
    created_at: datetime
    config: dict[str, object]
    parent_config: dict[str, object] | None


def test_normalize_execution_state_projects_interrupt_contract() -> None:
    """Normalize real LangGraph interrupt and task values without graph persistence."""
    approval_interrupt = Interrupt(
        value={"type": "approval", "request_id": "request-7"},
        id="interrupt-7",
    )
    state = _StateNormalizationFixture(
        next=("await_approval",),
        interrupts=(approval_interrupt,),
        tasks=(
            PregelTask(
                id="task-7",
                name="await_approval",
                path=("__pregel_pull", "await_approval"),
                interrupts=(approval_interrupt,),
            ),
        ),
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
        config={"configurable": {"checkpoint_id": "checkpoint-7"}},
        parent_config={"configurable": {"checkpoint_id": "checkpoint-6"}},
    )

    payload = StateProjector.normalize_execution_state(state)

    assert payload.checkpoint_id == "checkpoint-7"
    assert payload.parent_checkpoint_id == "checkpoint-6"
    assert payload.snapshot_created_at == "2026-08-02T00:00:00+00:00"
    assert payload.next_nodes == ["await_approval"]
    assert payload.interrupt_types == ["approval"]
    assert payload.interrupt_count == 1
    assert payload.task_count == 1
    task = payload.tasks[0]
    assert task.task_id == "task-7"
    assert task.name == "await_approval"
    assert task.path == ["__pregel_pull", "await_approval"]
    assert task.interrupt_ids == ["interrupt-7"]
    assert task.interrupt_types == ["approval"]
    assert not task.has_error
    assert not task.has_nested_state
    assert not task.has_result
