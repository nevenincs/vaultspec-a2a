"""Worker-relay events an api test delivers through the real internal relay route.

A stream test produces the frames it asserts on the way the worker does: by
posting worker-IPC envelopes to ``/internal/events/batch`` on the gateway under
test. The envelopes are built here once, so every resume and replay case relays
the same body shape and a sequence means the same thing in each of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    import httpx

__all__ = ["progress_event", "relay_events", "terminal_event"]


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


def terminal_event(run_id: str, index: int) -> dict[str, Any]:
    """The completed-terminal envelope for *run_id* at sequence *index*."""
    return {
        "thread_id": run_id,
        "ts": float(index),
        "payload": {
            "type": "thread_terminal",
            "event_type": "thread_terminal",
            "thread_id": run_id,
            "status": ThreadStatus.COMPLETED.value,
            "sequence": index,
        },
    }


async def relay_events(client: httpx.AsyncClient, events: list[dict[str, Any]]) -> None:
    """Deliver *events* through the gateway's real worker relay route."""
    response = await client.post("/internal/events/batch", json={"events": events})
    assert response.status_code == 200, response.text
