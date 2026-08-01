"""End-to-end tests for the mid-run clarification interrupt (agent-flow ADR D5).

Drives the real pieces together: a real ``StateGraph`` built on
``create_clarification_node()`` parks a genuine ``interrupt()`` against the
SAME ``AsyncSqliteSaver`` checkpointer the gateway app reads; ``GET
/v1/runs/{run_id}`` discloses it; ``POST .../clarifications/{request_id}/
respond`` answers it and dispatches a real resume to the in-process worker
ASGI app. No mocks: the worker is a real FastAPI app served over
``httpx.ASGITransport`` (matching the sibling permission-respond tests in
``test_endpoints.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ...graph.nodes.clarification import create_clarification_node
from ...streaming.aggregator import EventAggregator
from ...thread.state import TeamState
from .conftest import make_app

_BUNDLE_FREE_PRESET = "mock-success-single"

_QUESTIONS = [
    {
        "id": "provider",
        "prompt": "Which provider should author the plan?",
        "kind": "choice",
        "options": ["codex", "zai"],
        "required": True,
    },
    {"id": "scope", "prompt": "Which module should this target?", "kind": "text"},
]


def _clarification_graph(checkpointer: AsyncSqliteSaver) -> Any:
    """Compile a real, minimal graph around the clarification node."""
    builder: StateGraph = StateGraph(cast("Any", TeamState))
    builder.add_node("clarification", create_clarification_node())
    builder.add_edge(START, "clarification")
    builder.add_edge("clarification", END)
    return builder.compile(checkpointer=checkpointer)


async def _park_clarification(
    checkpointer: AsyncSqliteSaver, *, thread_id: str
) -> dict[str, Any]:
    """Run the real clarification graph to a park under *thread_id*.

    Returns the interrupt payload (with the generated ``request_id``).
    """
    graph = _clarification_graph(checkpointer)
    state: dict[str, Any] = {
        "active_agent": "clarification",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Ground the feature.")],
        "next": "",
        "thread_id": thread_id,
        "active_feature": "agent-panel",
        "token_usage": {},
        "clarification_questions": _QUESTIONS,
    }
    result = await graph.ainvoke(
        state, config={"configurable": {"thread_id": thread_id}}
    )
    assert "__interrupt__" in result, "clarification graph did not park"
    return result["__interrupt__"][0].value


class TestClarificationRoundTrip:
    """Park -> disclose -> respond -> resume, over the real graph."""

    def test_park_disclose_respond_resume(
        self, session_factory, checkpointer
    ) -> None:
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            payload = asyncio.run(
                _park_clarification(checkpointer, thread_id=thread_id)
            )
            request_id = payload["request_id"]

            # Disclosure: run-status discloses the pending clarification with
            # exactly the request id and question set the park produced.
            status_resp = client.get(f"/v1/runs/{thread_id}")
            assert status_resp.status_code == 200
            disclosed = status_resp.json()["pending_clarification"]
            assert disclosed is not None
            assert disclosed["request_id"] == request_id
            assert [q["id"] for q in disclosed["questions"]] == ["provider", "scope"]

            # Respond: a valid answer to the required choice question, the
            # optional text question left unanswered.
            respond_resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"provider": "codex"}},
            )

        assert respond_resp.status_code == 200
        body = respond_resp.json()
        assert body["accepted"] is True
        assert body["run_id"] == thread_id
        assert body["request_id"] == request_id

        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "resume"
        assert dispatch["thread_id"] == thread_id
        assert dispatch["option_id"] == {"provider": "codex"}

    def test_reload_recovery_from_status_disclosure_alone(
        self, session_factory, checkpointer
    ) -> None:
        """A second, independent app instance discloses the same pending question.

        No in-memory state is shared between the two ``make_app`` calls below
        beyond the durable session_factory/checkpointer — this is the reload
        proof: authoritative disclosure survives a fresh read with no relay
        frame and no prior request in scope.
        """
        app1, _agg1, worker1, _cp1 = make_app(session_factory, checkpointer)
        with TestClient(app1, raise_server_exceptions=True) as client1:
            create_resp = client1.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]

        payload = asyncio.run(_park_clarification(checkpointer, thread_id=thread_id))
        request_id = payload["request_id"]

        # A second, independent app — its own EventAggregator, its own
        # TestClient lifecycle — reading the SAME durable session_factory and
        # checkpointer, simulating a reload/reconnect.
        app2, _agg2, _worker2, _cp2 = make_app(
            session_factory, checkpointer, aggregator=EventAggregator()
        )
        with TestClient(app2, raise_server_exceptions=True) as client2:
            status_resp = client2.get(f"/v1/runs/{thread_id}")

        assert status_resp.status_code == 200
        disclosed = status_resp.json()["pending_clarification"]
        assert disclosed is not None
        assert disclosed["request_id"] == request_id
        assert disclosed["questions"][0]["options"] == ["codex", "zai"]

    def test_respond_rejects_missing_required_answer(
        self, session_factory, checkpointer
    ) -> None:
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            payload = asyncio.run(
                _park_clarification(checkpointer, thread_id=thread_id)
            )
            request_id = payload["request_id"]

            # The required "provider" question is left unanswered.
            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"scope": "graph/nodes/clarification.py"}},
            )

        assert resp.status_code == 409
        assert "provider" in resp.json()["detail"]
        assert worker.dispatches == []

    def test_respond_rejects_unknown_choice_option(
        self, session_factory, checkpointer
    ) -> None:
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            payload = asyncio.run(
                _park_clarification(checkpointer, thread_id=thread_id)
            )
            request_id = payload["request_id"]

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"provider": "not-a-real-provider"}},
            )

        assert resp.status_code == 409
        assert worker.dispatches == []

    def test_respond_to_unknown_request_id_is_not_found_or_conflict(
        self, session_factory, checkpointer
    ) -> None:
        """A guessed/stale request id must not silently succeed."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/nosuchrequest/respond",
                json={"answers": {"provider": "codex"}},
            )

        assert resp.status_code == 409
        assert worker.dispatches == []

    def test_respond_extra_answer_field_is_forbidden_by_the_wire_schema(
        self, session_factory, checkpointer
    ) -> None:
        """extra='forbid' — a field the schema does not declare 422s."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/some-id/respond",
                json={"answers": {"provider": "codex"}, "notes": "surprise field"},
            )

        assert resp.status_code == 422
        assert worker.dispatches == []
