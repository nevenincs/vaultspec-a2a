"""Worker-relay events an api test delivers through the real internal relay route.

A stream test produces the frames it asserts on the way the worker does: by
posting worker-IPC envelopes to ``/internal/events/batch`` on the gateway under
test. The envelopes are built here once, so every resume and replay case relays
the same body shape and a sequence means the same thing in each of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...database import get_control_action_by_dispatch_id, get_thread
from ...testing import record_completed_checkpoint
from ...thread.action_receipts import GraphActionReceipt
from ...thread.cancellation_evidence import CancellationEvidence
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    import httpx
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory, _InProcessWorker

__all__ = [
    "RelayContext",
    "progress_event",
    "relay_events",
    "relay_terminal",
    "terminal_event",
]


@dataclass(frozen=True, slots=True)
class RelayContext:
    """The gateway-side stores and recording worker a terminal is relayed against."""

    checkpointer: AsyncSqliteSaver
    worker: _InProcessWorker
    session_factory: SessionFactory


def progress_event(run_id: str, index: int) -> dict[str, Any]:
    """One agent-status progress envelope for *run_id* at sequence *index*."""
    return {
        "thread_id": run_id,
        "ts": float(index),
        "payload": {
            "type": "agent_status",
            "event_type": "agent_status",
            "thread_id": run_id,
            "agent_id": "coder",
            "state": "working",
            "detail": f"step {index}",
            "sequence": index,
        },
    }


def terminal_event(
    run_id: str,
    index: int | None = None,
    *,
    status: str = ThreadStatus.COMPLETED.value,
) -> dict[str, Any]:
    """The terminal envelope for *run_id*, numbered at *index* when one is given."""
    payload: dict[str, Any] = {
        "type": "thread_terminal",
        "event_type": "thread_terminal",
        "thread_id": run_id,
        "status": status,
    }
    envelope: dict[str, Any] = {"thread_id": run_id, "payload": payload}
    if index is not None:
        envelope["ts"] = float(index)
        payload["sequence"] = index
    return envelope


async def relay_events(client: httpx.AsyncClient, events: list[dict[str, Any]]) -> None:
    """Deliver *events* through the gateway's real worker relay route."""
    response = await client.post("/internal/events/batch", json={"events": events})
    assert response.status_code == 200, response.text


async def relay_terminal(
    client: httpx.AsyncClient,
    run_id: str,
    relay: RelayContext,
    *,
    status: str = ThreadStatus.COMPLETED.value,
) -> None:
    """Deliver a run's terminal event over the real worker relay endpoint.

    A completion carries the proof the gateway demands before it accepts one: the
    checkpoint the run's accepted action completed in. A cancellation carries the
    evidence naming the cancel dispatch the worker received.
    """
    envelope = terminal_event(run_id, status=status)
    payload = envelope["payload"]
    if status == ThreadStatus.COMPLETED.value:
        async with relay.session_factory() as db:
            thread = await get_thread(db, run_id)
            assert thread is not None
            action = await get_control_action_by_dispatch_id(
                db,
                thread_id=run_id,
                dispatch_id=thread.writer_action_receipt_id,
            )
            assert action is not None and action.graph_receipt_json is not None
            receipt = GraphActionReceipt.model_validate_json(action.graph_receipt_json)
        await record_completed_checkpoint(relay.checkpointer, receipt)
    elif status == ThreadStatus.CANCELLED.value:
        dispatch = next(
            item
            for item in reversed(relay.worker.dispatches)
            if item["thread_id"] == run_id and item["action"] == "cancel"
        )
        payload["cancellation_evidence"] = CancellationEvidence(
            schema_version="cancellation-evidence-v1",
            dispatch_id=str(dispatch["dispatch_id"]),
            outcome="no_active_work",
        ).model_dump(mode="json")
    await relay_events(client, [envelope])
