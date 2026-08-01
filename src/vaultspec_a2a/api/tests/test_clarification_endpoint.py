"""End-to-end tests for the mid-run clarification interrupt.

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
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...streaming.aggregator import EventAggregator
from ...thread.clarification import MAX_ANSWER_CHARS
from .clarification_harness import park_clarification
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_BUNDLE_FREE_PRESET = "mock-success-single"

type SessionFactory = async_sessionmaker[AsyncSession]


class TestClarificationRoundTrip:
    """Park -> disclose -> respond -> resume, over the real graph."""

    def test_park_disclose_respond_resume(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
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

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

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
        assert dispatch["option_id"] == {
            "type": "clarification_response",
            "request_id": request_id,
            "answers": {"provider": "codex"},
        }

    def test_reload_recovery_from_status_disclosure_alone(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """A second, independent app instance discloses the same pending question.

        No in-memory state is shared between the two ``make_app`` calls below
        beyond the durable session_factory/checkpointer — this is the reload
        proof: authoritative disclosure survives a fresh read with no relay
        frame and no prior request in scope.
        """
        app1, _agg1, _worker1, _cp1 = make_app(session_factory, checkpointer)
        with TestClient(app1, raise_server_exceptions=True) as client1:
            create_resp = client1.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]

        parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
        request_id = parked.request.request_id

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
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            # The required "provider" question is left unanswered.
            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"scope": "graph/nodes/clarification.py"}},
            )

        assert resp.status_code == 422
        assert "provider" in resp.json()["detail"]
        assert worker.dispatches == []

    def test_respond_rejects_unknown_choice_option(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"provider": "not-a-real-provider"}},
            )

        assert resp.status_code == 422
        assert worker.dispatches == []

    def test_respond_to_unknown_request_id_is_not_found_or_conflict(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
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

        assert resp.status_code == 404
        assert worker.dispatches == []

    def test_respond_refuses_a_newline_in_a_free_text_answer(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """A ``text`` answer is free prose, but it is single-line free prose.

        The one surface that renders this questionnaire renders a text answer
        as a single-line input by deliberate contract, and the edge in front of
        this route refuses a control character in the same value. A newline
        therefore cannot come from the sanctioned client at all, and admitting
        one here would mean two callers of the same route get two behaviours.
        """
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={
                    "answers": {
                        "provider": "codex",
                        "scope": "first line\nsecond line",
                    }
                },
            )

        assert resp.status_code == 422
        # Refused at the wire model, before any run state was touched: the run
        # stays parked on its question rather than resuming on a mangled answer.
        assert worker.dispatches == []

    def test_respond_refuses_a_tab_in_an_answer(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """Tab is a control character here, exactly as it is at the edge.

        The sharp edge of the rule and the reason it is worth its own test: tab
        was once excepted on the question-producing side while the edge refused
        it in an answer, which is the asymmetry that could offer a ``choice``
        option no admissible answer could match.
        """
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"provider": "codex", "scope": "graph\tnodes"}},
            )

        assert resp.status_code == 422
        assert worker.dispatches == []

    def test_respond_refuses_a_mixture_and_takes_the_clean_equivalent(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """The same sheet fails dirty and succeeds clean.

        Paired deliberately: a refusal test alone cannot tell "the control
        character was refused" from "this sheet was never acceptable", so the
        identical sheet with the control characters removed is driven straight
        after and must resume the run.
        """
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            dirty = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={
                    "answers": {
                        "provider": "codex",
                        "scope": "tab\there\nand a newline\x7fand a del",
                    }
                },
            )
            assert dirty.status_code == 422
            assert worker.dispatches == []

            clean = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={
                    "answers": {
                        "provider": "codex",
                        "scope": "tabhereand a newlineand a del",
                    }
                },
            )

        assert clean.status_code == 200
        assert len(worker.dispatches) == 1
        assert worker.dispatches[0]["option_id"]["answers"] == {
            "provider": "codex",
            "scope": "tabhereand a newlineand a del",
        }

    def test_respond_counts_the_answer_cap_in_characters_not_bytes(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """A multibyte answer sitting exactly on the cap is accepted.

        The cap is a CHARACTER count on both sides of this boundary. A
        byte-counting implementation would refuse this answer at roughly a
        third of the length the contract promises, and would do it only for
        non-ASCII text - so the ceiling is asserted with characters that do not
        fit in one byte, which is the only way the distinction is visible.
        """
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)
        # Three bytes each in UTF-8; a byte-based cap would refuse this at
        # MAX_ANSWER_CHARS characters.
        at_the_cap = "世" * MAX_ANSWER_CHARS
        assert len(at_the_cap.encode()) > MAX_ANSWER_CHARS

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"provider": "codex", "scope": at_the_cap}},
            )

        assert resp.status_code == 200
        assert worker.dispatches[0]["option_id"]["answers"]["scope"] == at_the_cap

    def test_respond_refuses_one_character_over_the_cap(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """The other half of the cap: a ceiling that never refuses is not one."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={
                    "answers": {
                        "provider": "codex",
                        "scope": "a" * (MAX_ANSWER_CHARS + 1),
                    }
                },
            )

        assert resp.status_code == 422
        assert worker.dispatches == []

    def test_respond_extra_answer_field_is_forbidden_by_the_wire_schema(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
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

    @pytest.mark.parametrize(
        "answer", ["codex\nand a second line", "codex\tand a tab", "codex\x7fdel"]
    )
    def test_respond_refuses_a_control_bearing_answer_at_the_wire(
        self,
        session_factory: SessionFactory,
        checkpointer: AsyncSqliteSaver,
        answer: str,
    ) -> None:
        """A control character in an answer 422s before any run state is read.

        The request id below is deliberately one that does not exist: a 404
        would mean the schema admitted the answer and the route got as far as
        resolving the questionnaire, so the 422 is what proves the bound bit at
        the wire rather than a step later. The empty dispatch list is the other
        half of that proof - nothing was resumed on the way to refusing.
        """
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
                json={"answers": {"provider": answer}},
            )

        assert resp.status_code == 422
        assert "control characters" in resp.text
        assert worker.dispatches == []

    def test_respond_takes_an_ordinary_answer_over_the_same_route(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """The bound refuses control characters and nothing more.

        The negative case above would also pass against a schema that refused
        every answer, so the positive case is what proves the refusal is
        selective: the same route, the same shape, an answer without a control
        character, and the run resumes.
        """
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "plan it"},
            )
            thread_id = create_resp.json()["run_id"]
            worker.dispatches.clear()

            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            request_id = parked.request.request_id

            resp = client.post(
                f"/v1/runs/{thread_id}/clarifications/{request_id}/respond",
                json={"answers": {"provider": "codex", "scope": "a b"}},
            )

        assert resp.status_code == 200
        assert worker.dispatches != []
