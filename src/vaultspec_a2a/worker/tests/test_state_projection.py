"""State-normalization contract coverage for execution-state projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Interrupt, PregelTask
from pydantic import BaseModel, ConfigDict

from ...providers import ProviderCondition
from ...thread.enums import ThreadStatus
from ..ipc import WorkerBridge
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


def test_normalize_state_keeps_missing_configurable_metadata_optional() -> None:
    """A checkpoint without configurable metadata remains a valid empty projection."""
    state = _StateNormalizationFixture(
        next=(),
        interrupts=(),
        tasks=(),
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
        config={},
        parent_config=None,
    )

    payload = StateProjector.normalize_execution_state(state)

    assert payload.checkpoint_id is None
    assert payload.parent_checkpoint_id is None


def test_normalize_state_raises_for_malformed_configurable_metadata() -> None:
    """A present non-mapping configurable value raises for emitter degradation."""
    state = _StateNormalizationFixture(
        next=(),
        interrupts=(),
        tasks=(),
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
        config={"configurable": []},
        parent_config=None,
    )

    with pytest.raises(TypeError, match="configurable metadata"):
        StateProjector.normalize_execution_state(state)


def _relayed_terminal_projector(
    relayed: list[dict[str, Any]],
) -> StateProjector:
    """Build a projector whose bridge posts to a real in-process gateway.

    The terminal event is what the gateway persists, so the assertions below are
    on the JSON that actually crossed the worker-to-gateway hop - a real
    ``WorkerBridge`` serialising over real HTTP into a real ASGI app - rather
    than on a dictionary handed straight back to the test.
    """
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        body = await request.json()
        relayed.extend(body["events"])
        return Response(content='{"status":"ok"}', media_type="application/json")

    bridge = WorkerBridge(api_url="http://control:8000", worker_id="projector-test")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://control:8000",
    )
    return StateProjector(checkpointer=InMemorySaver(), bridge=bridge)


class TestTerminalConditionCarriage:
    """The condition rides the terminal event the gateway persists.

    The error frame that also carries it is droppable, so this payload is the
    only channel a reloading client can recover the condition from.
    """

    @pytest.mark.asyncio
    async def test_a_failed_terminal_carries_the_condition_it_was_given(self) -> None:
        """A classified failure reports the lane's own verdict, not the floor."""
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)

        await projector.emit_terminal_status(
            "thread-throttled",
            ThreadStatus.FAILED,
            error_detail="the provider refused for rate",
            provider_condition=ProviderCondition.THROTTLED,
        )

        assert len(relayed) == 1
        payload = relayed[0]["payload"]
        assert payload["status"] == ThreadStatus.FAILED.value
        assert payload["provider_condition"] == ProviderCondition.THROTTLED.value
        assert payload["error_detail"] == "the provider refused for rate"

    @pytest.mark.asyncio
    async def test_a_failed_terminal_never_leaves_the_condition_absent(self) -> None:
        """The floor is applied here so no call site can omit the field.

        Every pre-run refusal in the executor fails a run without observing a
        provider. Depending on each of them to remember a condition is how the
        blank terminal this campaign removes came about in the first place.
        """
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)

        await projector.emit_terminal_status(
            "thread-unclassified",
            ThreadStatus.FAILED,
            error_detail="no graph to run",
        )

        assert len(relayed) == 1
        assert (
            relayed[0]["payload"]["provider_condition"]
            == ProviderCondition.UNKNOWN.value
        )

    @pytest.mark.asyncio
    async def test_a_completed_terminal_carries_no_condition_at_all(self) -> None:
        """A run that did not fail has no provider failure to classify.

        Stamping the unknown member on a successful run would read as a
        provider failure nobody observed.
        """
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)

        await projector.emit_terminal_status("thread-ok", ThreadStatus.COMPLETED)

        assert len(relayed) == 1
        assert "provider_condition" not in relayed[0]["payload"]
