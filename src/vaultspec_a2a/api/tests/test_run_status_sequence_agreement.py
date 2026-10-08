"""The cursor run-status serves is the id the run's last frame carried.

One number read two ways. ``run-status`` publishes ``last_sequence`` as the
position a consumer has seen everything up to; the stream publishes the same
position as the SSE ``id`` of each frame. A consumer that stores the cursor and
resumes from it is relying on the two being the same number, so a settled run
whose cursor sits below its own terminal frame hands that consumer a position
one frame short - and the frame it misses is the terminal, the one frame of a
run that matters most.

Driven end to end against a real uvicorn server, a real migrated SQLite store
and the real internal relay route the worker posts to, because the agreement is
between what one request WRITES at settle and what another request SERVES.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ...streaming import RelayHub
from ...testing import (
    DEFAULT_TEAM_PRESET,
    SseReader,
    async_catalog_run_fields,
    serve_on_loopback,
)
from ...thread.enums import ThreadStatus
from ._relay_events import RelayContext, progress_event, relay_events, relay_terminal
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RUN = "sequence-agreement-run"


async def _start_run(client: httpx.AsyncClient, run_id: str) -> None:
    """Start one real run through the versioned verb."""
    fields = await async_catalog_run_fields(client)
    started = await client.post(
        "/v1/runs",
        json={
            "run_id": run_id,
            "team_preset": DEFAULT_TEAM_PRESET,
            "message": "produce a few frames and then finish",
            **fields,
        },
    )
    assert started.status_code == 201, started.text


@pytest.mark.asyncio(loop_scope="function")
async def test_settled_last_sequence_equals_the_terminal_frames_sse_id(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The settled cursor names the terminal frame, not the frame before it.

    The terminal is held by the relay until the control plane proves the run
    really ended, so its number is taken on the far side of the write that
    records the cursor. Reserving the number before that write is what keeps
    the two in agreement; capturing the mark first left the cursor exactly one
    short of the id the client had just been handed.
    """
    app, _hub, worker, _cp = make_app(session_factory, checkpointer, RelayHub())

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await _start_run(client, _RUN)
        async with client.stream("GET", f"/v1/runs/{_RUN}/stream") as response:
            assert response.status_code == 200
            reader = SseReader(response.aiter_lines())
            assert (await reader.next_frame()).type == "stream_snapshot"
            await relay_events(
                client, [progress_event(_RUN, index) for index in (1, 2)]
            )
            progress = [await reader.next_frame() for _ in range(2)]
            await relay_terminal(
                client, _RUN, RelayContext(checkpointer, worker, session_factory)
            )
            terminal = await reader.next_frame()
        settled = await client.get(f"/v1/runs/{_RUN}")

    assert [frame.event_id for frame in progress] == [f"{_RUN}:1", f"{_RUN}:2"]
    assert terminal.type == "thread_terminal"
    assert terminal.event_id == f"{_RUN}:3", (
        "the terminal frame must carry the next number after the run's progress"
    )
    assert settled.status_code == 200, settled.text
    body = settled.json()
    assert body["status"] == ThreadStatus.COMPLETED.value
    assert body["last_sequence"] == 3, (
        "run-status serves a cursor below the terminal frame's own id: "
        f"last_sequence={body['last_sequence']}, terminal id={terminal.event_id}"
    )
