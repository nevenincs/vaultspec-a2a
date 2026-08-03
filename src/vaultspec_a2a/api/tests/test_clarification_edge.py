"""The mid-run clarification edge, end to end over the real surfaces.

Nothing here is simulated. A REAL LangGraph clarification node pair parks a run
on a REAL ``interrupt()`` written into the SAME ``AsyncSqliteSaver`` the app
reads through, a REAL SQLite thread record backs the run, and the answering verb
is exercised over REAL HTTP against the real FastAPI app, with the resulting
dispatch captured by the conftest's real in-process worker.

That end-to-end shape is the point. Asserting the route in isolation would prove
only that the route can format a response; what has to hold is that the question
a graph is genuinely parked on is the question ``run-status`` discloses, and that
the answers posted back arrive at the worker as the typed resume value the parked
node will read.
"""

from __future__ import annotations

import itertools
from typing import Any, cast

import httpx
import pytest
from httpx import ASGITransport
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from ...graph.nodes.clarification import (
    create_clarification_gate_node,
    create_clarification_request_node,
)
from ...thread.clarification import (
    MAX_ANSWER_CHARS,
    ClarificationKind,
    ClarificationQuestion,
    ClarificationRequest,
)
from ...thread.state import TeamState
from .conftest import async_catalog_run_fields, make_app

_PRESET = "mock-success-single"


def _question_set(request_id: str) -> ClarificationRequest:
    return ClarificationRequest(
        request_id=request_id,
        questions=[
            ClarificationQuestion(
                id="dock_side",
                prompt="Which side should the monitor panel dock to?",
                kind=ClarificationKind.CHOICE,
                options=["right", "left"],
            ),
            ClarificationQuestion(
                id="notes",
                prompt="Anything else the panel must respect?",
                kind=ClarificationKind.TEXT,
                required=False,
            ),
        ],
    )


async def _park_on_clarification(
    checkpointer: Any, *, thread_id: str, request_id: str
) -> None:
    """Park a real graph on a real clarification interrupt in the real store.

    Writes through the app's own checkpointer, so what the gateway later reads is
    literally what a parked run left behind - not a hand-built row shaped to
    resemble one.
    """
    request = _question_set(request_id)

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

    await graph.ainvoke(
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
        config={"configurable": {"thread_id": thread_id}},
    )


_RUN_SEQ = itertools.count(1)


async def _start_run(client: httpx.AsyncClient) -> str:
    """Start one run, giving each call its own id.

    Every test in this module starts through here, so the id must vary per
    CALL rather than per site: a shared one would make the second test's start
    a replay of the first's run instead of a run of its own.
    """
    response = await client.post(
        "/v1/runs",
        json={
            "team_preset": _PRESET,
            "message": "plan it",
            "autonomous": True,
            "run_id": f"clarify-edge-{next(_RUN_SEQ):02d}",
            **await async_catalog_run_fields(client),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


@pytest.mark.asyncio
async def test_run_status_discloses_the_parked_questionnaire(
    session_factory, checkpointer
) -> None:
    """Recovery re-renders the questionnaire from authoritative state.

    This is the disclosure the whole design turns on: a client that reloaded and
    never saw a progress frame still learns the exact question set, its request
    id, and each question's kind, options, and required flag - because it reads
    the run's own checkpoint through run-status rather than a droppable relay.
    """
    app, _agg, _worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(cp, thread_id=run_id, request_id="clarify-status")

        status = await client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200, status.text
        body = status.json()

    assert body["pending_clarification"] == {
        "type": "clarification_request",
        "request_id": "clarify-status",
        "questions": [
            {
                "id": "dock_side",
                "prompt": "Which side should the monitor panel dock to?",
                "kind": "choice",
                "options": ["right", "left"],
                "required": True,
            },
            {
                "id": "notes",
                "prompt": "Anything else the panel must respect?",
                "kind": "text",
                "options": None,
                "required": False,
            },
        ],
    }
    # The pause cause names the interrupt the run is genuinely parked on, so the
    # disclosure and the topology position agree about why it stopped.
    assert body["topology"]["pause_cause"] == "clarification_request"


@pytest.mark.asyncio
async def test_run_status_discloses_nothing_when_no_question_is_pending(
    session_factory, checkpointer
) -> None:
    """A run with no parked question must not fabricate one."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        status = await client.get(f"/v1/runs/{run_id}")

    assert status.status_code == 200
    assert status.json()["pending_clarification"] is None


@pytest.mark.asyncio
async def test_answers_reach_the_worker_as_the_typed_resume_value(
    session_factory, checkpointer
) -> None:
    """The verb maps the answer sheet onto ``Command(resume=...)``, not a turn.

    The assertion is on what the REAL worker received: a resume dispatch whose
    option carries the typed clarification response keyed by question id. A
    follow-up message turn - the shape this verb deliberately is not - would
    arrive as an ingest carrying prose, so the dispatch body is what separates
    the two.
    """
    app, _agg, worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(cp, thread_id=run_id, request_id="clarify-answer")
        worker.clear()

        response = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-answer/respond",
            json={"answers": {"dock_side": "right", "notes": "keep it collapsible"}},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "api_version": "v1",
        "run_id": run_id,
        "request_id": "clarify-answer",
        "accepted": True,
        "applied": False,
        "action_status": "accepted_not_applied",
        "idempotency_key": "clarification-response:clarify-answer",
    }

    assert len(worker.dispatches) == 1
    dispatch = worker.dispatches[0]
    assert dispatch["action"] == "resume"
    assert dispatch["thread_id"] == run_id
    assert dispatch["option_id"] == {
        "type": "clarification_response",
        "request_id": "clarify-answer",
        "answers": {"dock_side": "right", "notes": "keep it collapsible"},
    }


@pytest.mark.asyncio
async def test_answering_a_question_no_run_is_parked_on_is_refused(
    session_factory, checkpointer
) -> None:
    """A run that is not waiting has nothing to answer, and nothing is dispatched."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        worker.clear()

        response = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-absent/respond",
            json={"answers": {"dock_side": "right"}},
        )

    assert response.status_code == 404
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_a_guessed_request_id_cannot_answer_a_parked_question(
    session_factory, checkpointer
) -> None:
    """Scoping precedes acting, so a mismatched id has no effect at all."""
    app, _agg, worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(cp, thread_id=run_id, request_id="clarify-real")
        worker.clear()

        response = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-guessed/respond",
            json={"answers": {"dock_side": "right"}},
        )

        assert response.status_code == 404
        assert worker.dispatches == []

        # The run is still parked on its own question, untouched by the attempt.
        status = await client.get(f"/v1/runs/{run_id}")

    assert status.json()["pending_clarification"]["request_id"] == "clarify-real"


@pytest.mark.asyncio
async def test_a_choice_outside_its_declared_options_is_refused(
    session_factory, checkpointer
) -> None:
    """The declared options bound the answer; an invented one never dispatches."""
    app, _agg, worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(cp, thread_id=run_id, request_id="clarify-bounds")
        worker.clear()

        response = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-bounds/respond",
            json={"answers": {"dock_side": "diagonal"}},
        )

    assert response.status_code == 422
    assert "dock_side" in response.json()["detail"]
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_a_required_question_left_blank_is_refused(
    session_factory, checkpointer
) -> None:
    """A questionnaire that skips a required question is not an answer."""
    app, _agg, worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(
            cp, thread_id=run_id, request_id="clarify-required"
        )
        worker.clear()

        response = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-required/respond",
            json={"answers": {"notes": "only the optional one"}},
        )

    assert response.status_code == 422
    assert "required" in response.json()["detail"]
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_an_over_long_answer_is_refused_at_the_wire(
    session_factory, checkpointer
) -> None:
    """The cap is enforced by the type, before any run state is touched.

    The refusal is a 422 from the wire model itself rather than a check inside
    the route, which is what makes the bound a contract instead of a convention:
    it cannot be bypassed by a call path that forgets to apply it.

    Sized from :data:`MAX_ANSWER_CHARS` rather than from a literal, and asserting
    BOTH sides of the ceiling. This test used to post a hardcoded ``"x" * 4096``,
    which publishes the number 4096 next to the word "cap" in a file a consumer
    reads to learn a2a's bounds - the engine adopted 4096 as this side's answer
    cap and the dashboard mirrored the engine, while a2a has never enforced
    anything but 2048.

    It also could not fail. It answered only the OPTIONAL ``notes`` question, so
    the required ``dock_side`` was left blank: delete the length cap entirely and
    the request still 422s, from the required-question check one layer later.
    Both answers are supplied below so the length is the only thing left to
    object to, which is what makes the refusal evidence about the cap.
    """
    app, _agg, worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(cp, thread_id=run_id, request_id="clarify-cap")
        worker.clear()

        over = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-cap/respond",
            json={
                "answers": {
                    "dock_side": "right",
                    "notes": "x" * (MAX_ANSWER_CHARS + 1),
                }
            },
        )
        assert over.status_code == 422
        assert worker.dispatches == []

        # The ceiling itself is admitted. A cap is two behaviours, and a test
        # that only drives the refusal cannot tell a correct bound from one set
        # a character too low.
        at_ceiling = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-cap/respond",
            json={"answers": {"dock_side": "right", "notes": "x" * MAX_ANSWER_CHARS}},
        )

    assert at_ceiling.status_code == 200
    assert worker.dispatches != []


@pytest.mark.asyncio
async def test_the_answered_questionnaire_stops_being_disclosed(
    session_factory, checkpointer
) -> None:
    """Once answered and resumed, the question is no longer pending.

    The graph is resumed here through its own ``Command`` rather than through the
    verb's dispatch (the conftest worker records dispatches instead of executing
    them), so this pins the half the verb hands off to: an answered run parks on
    nothing, which is exactly what makes the parked interrupt an at-most-once
    guard for the answering verb.
    """
    from langgraph.types import Command

    app, _agg, _worker, cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        run_id = await _start_run(client)
        await _park_on_clarification(cp, thread_id=run_id, request_id="clarify-settle")

        parked = await client.get(f"/v1/runs/{run_id}")
        assert parked.json()["pending_clarification"] is not None

        request = _question_set("clarify-settle")

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
            "clarification_gate",
            create_clarification_gate_node(proceed_target="proceed"),
        )
        builder.add_node("proceed", proceed)
        builder.add_edge(START, "clarification_request")
        builder.add_edge("proceed", END)
        graph = builder.compile(checkpointer=cp)

        await graph.ainvoke(
            Command(
                resume={
                    "type": "clarification_response",
                    "request_id": "clarify-settle",
                    "answers": {"dock_side": "left"},
                }
            ),
            config={"configurable": {"thread_id": run_id}},
        )

        settled = await client.get(f"/v1/runs/{run_id}")
        assert settled.json()["pending_clarification"] is None

        replayed = await client.post(
            f"/v1/runs/{run_id}/clarifications/clarify-settle/respond",
            json={"answers": {"dock_side": "right"}},
        )

    assert replayed.status_code == 404
