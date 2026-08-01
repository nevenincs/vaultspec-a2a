"""The clarification nudge as a dashboard actually receives it: over the wire.

Driven through a REAL uvicorn server on a real TCP socket rather than
``ASGITransport``, because the transport buffers a whole response before
returning and an SSE consumer must read frames while the producer is still
emitting. The run is parked by the production clarification node pair on the
app's own checkpointer, and the frame is projected by the app's own aggregator,
so what these tests read off the socket is what a consumer reads.

The pair of assertions here is the whole design in one place: the SSE frame says
only THAT a question is waiting, and ``run-status`` says WHAT it asks. Proving
each half in isolation would miss the property that matters - that the question
text exists on exactly one of the two surfaces, and it is not the droppable one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
import uvicorn
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from ...graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ...streaming.transformer import emit_interrupt_events
from ...thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
)
from ...thread.state import TeamState
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ...streaming.types import StreamableGraph

_PRESET = "mock-success-single"
_PROMPT = "Which side should the monitor panel dock to?"
_OPTIONS = ["dock-right", "dock-left"]
_REQUEST_ID = "clarify-sse"


@contextlib.asynccontextmanager
async def _live_server(app) -> AsyncIterator[str]:
    """Serve *app* on an ephemeral port and yield its base URL."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started and server.servers:
                break
            await asyncio.sleep(0.01)
        assert server.started and server.servers, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5.0)


async def _read_event(
    lines: AsyncIterator[str], *, wanted: str, timeout: float = 10.0
) -> dict:
    """Read SSE ``data:`` frames until one whose ``type`` matches *wanted*."""

    async def _scan() -> dict:
        buffer: list[str] = []
        async for raw in lines:
            line = raw.rstrip("\r")
            if line.startswith("data: "):
                buffer.append(line.removeprefix("data: "))
                continue
            if line == "" and buffer:
                payload = json.loads("".join(buffer))
                buffer = []
                if payload.get("type") == wanted:
                    return payload
        raise AssertionError(f"stream ended before a {wanted!r} frame")

    return await asyncio.wait_for(_scan(), timeout=timeout)


async def _park_real_run(aggregator, checkpointer, *, thread_id: str) -> None:
    """Park a real run on a real clarification and project it through the app.

    Uses the production node pair and the app's own checkpointer and aggregator,
    so the frame that reaches the socket is produced by the same seam a live run
    goes through.
    """
    request = ClarificationRequest(
        request_id=_REQUEST_ID,
        questions=[
            ClarificationQuestion(
                id="dock_side",
                prompt=_PROMPT,
                kind=ClarificationKind.CHOICE,
                options=_OPTIONS,
            )
        ],
    )

    async def _producer(state: TeamState) -> ClarificationRequest | None:
        return request

    async def proceed(state: TeamState) -> dict[str, Any]:
        return {}

    builder: StateGraph = StateGraph(cast("Any", TeamState))
    builder.add_node(
        "clarification_request",
        create_clarification_request_node(
            _producer, gate_target="clarification_gate", proceed_target="proceed"
        ),
    )
    builder.add_node(
        "clarification_gate", create_clarification_gate_node(proceed_target="proceed")
    )
    builder.add_node("proceed", proceed)
    builder.add_edge(START, "clarification_request")
    builder.add_edge("proceed", END)
    graph = builder.compile(checkpointer=checkpointer)

    config: Any = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        {
            "active_agent": "clarify",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Plan the monitor panel.")],
            "next": "",
            "thread_id": thread_id,
            "active_feature": "agent-panel",
            "token_usage": {},
        },
        config=config,
    )
    assert "__interrupt__" in result

    emitted = await emit_interrupt_events(
        thread_id,
        "supervisor",
        cast("StreamableGraph", graph),
        config,
        aggregator._emitters,
    )
    assert emitted


@pytest.mark.asyncio(loop_scope="function")
async def test_the_nudge_arrives_on_the_sse_stream_carrying_no_questions(
    session_factory, checkpointer
) -> None:
    """A subscriber really receives the frame, and it really is only a nudge.

    The frame is read off a live socket, then the questionnaire's own strings are
    searched for in the raw frame. A consumer that could reconstruct the
    questions from this has been handed authority the relay is not allowed to
    carry, because the relay may drop it.
    """
    app, aggregator, _worker, cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=15.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={"team_preset": _PRESET, "message": "plan it", "autonomous": True},
        )
        assert start.status_code == 201, start.text
        run_id = str(start.json()["run_id"])

        async with client.stream("GET", f"/v1/runs/{run_id}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            lines = resp.aiter_lines()

            # Subscribe first, then park: the relay is live, not replayed.
            await asyncio.sleep(0.2)
            await _park_real_run(aggregator, cp, thread_id=run_id)

            frame = await _read_event(lines, wanted="clarification-pending")

    assert frame["thread_id"] == run_id
    assert frame["request_id"] == _REQUEST_ID

    raw = json.dumps(frame)
    assert _PROMPT not in raw
    for option in _OPTIONS:
        assert option not in raw
    assert "questions" not in frame


@pytest.mark.asyncio(loop_scope="function")
async def test_the_questions_live_on_run_status_not_on_the_relay(
    session_factory, checkpointer
) -> None:
    """The authority split, asserted as one property rather than two halves.

    Same parked run, both surfaces: the relay frame carries the correlation
    handle alone, and the status snapshot carries the questionnaire. This is what
    lets a client that reloaded - and so missed every frame ever sent - still
    render the question.
    """
    app, aggregator, _worker, cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=15.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={"team_preset": _PRESET, "message": "plan it", "autonomous": True},
        )
        assert start.status_code == 201, start.text
        run_id = str(start.json()["run_id"])

        async with client.stream("GET", f"/v1/runs/{run_id}/stream") as resp:
            lines = resp.aiter_lines()
            await asyncio.sleep(0.2)
            await _park_real_run(aggregator, cp, thread_id=run_id)
            frame = await _read_event(lines, wanted="clarification-pending")

        # A client that never saw the frame recovers everything from here.
        status = await client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200
        pending = status.json()["pending_clarification"]

    assert frame["request_id"] == pending["request_id"] == _REQUEST_ID
    # The relay knows only THAT; the snapshot knows WHAT.
    assert pending["questions"][0]["prompt"] == _PROMPT
    assert pending["questions"][0]["options"] == _OPTIONS
    assert _PROMPT not in json.dumps(frame)
