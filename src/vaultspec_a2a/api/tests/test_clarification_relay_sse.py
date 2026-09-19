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
import itertools
import json
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from langchain_core.messages import HumanMessage

from ...graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ...streaming.transformer import emit_interrupt_events
from ...testing.sse import read_frame
from ...thread.clarification import (
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
)
from .clarification_harness import new_state_graph
from .conftest import SessionFactory, _live_server, async_catalog_run_fields, make_app

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ...streaming.aggregator import EventAggregator
    from ...thread.state import TeamState

_PRESET = "mock-success-single"
_RUN_SEQ = itertools.count(1)
_PROMPT = "Which side should the monitor panel dock to?"
_OPTIONS = ["dock-right", "dock-left"]
_REQUEST_ID = "clarify-sse"


async def _park_real_run(
    aggregator: EventAggregator, checkpointer: AsyncSqliteSaver, *, thread_id: str
) -> None:
    """Park a real run on a real clarification and project it through the app.

    Uses the production node pair and the app's own checkpointer and aggregator,
    so the frame that reaches the socket is produced by the same seam a live run
    goes through. Builds its graph through the shared harness's typed
    ``new_state_graph`` boundary rather than constructing ``StateGraph``
    directly, matching the pattern already proven clean in
    ``clarification_harness.py``.
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
        del state
        return request

    def _proceed(state: TeamState) -> dict[str, object]:
        del state
        return {}

    builder = new_state_graph()
    builder.add_node(
        "clarification_request",
        create_clarification_request_node(
            _producer, gate_target="clarification_gate", proceed_target="proceed"
        ),
    )
    builder.add_node(
        "clarification_gate", create_clarification_gate_node(proceed_target="proceed")
    )
    builder.add_node("proceed", _proceed)
    builder.add_edge("__start__", "clarification_request")
    builder.add_edge("proceed", "__end__")
    graph = builder.compile(checkpointer=checkpointer)

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    state: TeamState = {
        "active_agent": "clarify",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Plan the monitor panel.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "agent-panel",
        "token_usage": {},
    }
    result = await graph.ainvoke(state, config=config)
    assert isinstance(result, dict)
    assert "__interrupt__" in result

    emitted = await emit_interrupt_events(
        thread_id,
        "supervisor",
        graph,
        cast("dict[str, Any]", config),
        aggregator._emitters,
    )
    assert emitted


@pytest.mark.asyncio(loop_scope="function")
async def test_the_nudge_arrives_on_the_sse_stream_carrying_no_questions(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
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
            json={
                "team_preset": _PRESET,
                "message": "plan it",
                "autonomous": True,
                "run_id": f"clarify-sse-{next(_RUN_SEQ):02d}",
                **await async_catalog_run_fields(client),
            },
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

            frame, _raw = await read_frame(
                lines, wanted="clarification_pending", timeout=10.0
            )

    assert frame["thread_id"] == run_id
    assert frame["request_id"] == _REQUEST_ID

    raw = json.dumps(frame)
    assert _PROMPT not in raw
    for option in _OPTIONS:
        assert option not in raw
    assert "questions" not in frame


@pytest.mark.asyncio(loop_scope="function")
async def test_the_questions_live_on_run_status_not_on_the_relay(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
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
            json={
                "team_preset": _PRESET,
                "message": "plan it",
                "autonomous": True,
                "run_id": f"clarify-sse-{next(_RUN_SEQ):02d}",
                **await async_catalog_run_fields(client),
            },
        )
        assert start.status_code == 201, start.text
        run_id = str(start.json()["run_id"])

        async with client.stream("GET", f"/v1/runs/{run_id}/stream") as resp:
            lines = resp.aiter_lines()
            await asyncio.sleep(0.2)
            await _park_real_run(aggregator, cp, thread_id=run_id)
            frame, _raw = await read_frame(
                lines, wanted="clarification_pending", timeout=10.0
            )

        # A client that never saw the frame recovers everything from here.
        status = await client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200
        pending = status.json()["pending_clarification"]

    assert frame["request_id"] == pending["request_id"] == _REQUEST_ID
    # The relay knows only THAT; the snapshot knows WHAT.
    assert pending["questions"][0]["prompt"] == _PROMPT
    assert pending["questions"][0]["options"] == _OPTIONS
    assert _PROMPT not in json.dumps(frame)
