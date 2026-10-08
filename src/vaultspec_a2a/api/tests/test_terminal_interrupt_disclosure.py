"""A settled run discloses nothing it was parked on.

Drives the real surfaces: a real graph parks a genuine ``interrupt()`` against
the same ``AsyncSqliteSaver`` the gateway reads, the run is then cancelled
through the production status election, and ``GET /v1/runs/{run_id}`` and
``GET /v1/runs/{run_id}/history`` are asked what the run is waiting on.

Nothing can answer a settled run: the respond verbs refuse it, so a disclosed
questionnaire or pending permission is an offer no caller can take up. Both
readings serve the same capture, so both are asserted against the same run.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...testing import (
    DEFAULT_TEAM_PRESET,
    catalog_run_fields,
    elect_status,
    park_clarification,
    park_journaled_permission,
)
from ...thread.enums import ThreadStatus
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


type SessionFactory = async_sessionmaker[AsyncSession]

_ALLOW_ONCE_OFFER: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"}
]


def _start_run(client: TestClient, run_id: str) -> str:
    """Start a real run over the gateway and name it."""
    response = client.post(
        "/v1/runs",
        json={
            "team_preset": DEFAULT_TEAM_PRESET,
            "message": "park then cancel",
            "run_id": run_id,
            **catalog_run_fields(client),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def _cancel(session_factory: SessionFactory, thread_id: str) -> None:
    """Settle *thread_id* as cancelled through the production election."""
    async with session_factory() as session:
        await elect_status(session, thread_id, ThreadStatus.CANCELLED)
        await session.commit()


class TestTerminalInterruptDisclosure:
    """A cancelled run offers neither its clarification nor its permissions."""

    def test_cancelled_run_discloses_no_parked_clarification(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """The questionnaire a cancelled run parked on is not served anywhere.

        The checkpoint still holds the parked request - cancelling a run does
        not rewrite its history - so the gate has to be in the read, not in the
        store.
        """
        app, _hub, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            thread_id = _start_run(client, "terminal-disclosure-clarify")
            parked = asyncio.run(park_clarification(checkpointer, thread_id=thread_id))
            assert parked.request.request_id
            asyncio.run(_cancel(session_factory, thread_id))

            status = client.get(f"/v1/runs/{thread_id}")
            history = client.get(f"/v1/runs/{thread_id}/history")

        assert status.status_code == 200, status.text
        status_body = status.json()
        assert status_body["status"] == ThreadStatus.CANCELLED.value
        assert status_body["pending_clarification"] is None
        assert status_body["topology"]["pause_cause"] is None

        assert history.status_code == 200, history.text
        state = history.json()["state"]
        assert state["pending_clarification"] is None
        assert state["pause_cause"] is None

    def test_cancelled_run_discloses_no_pending_permission(
        self, session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
    ) -> None:
        """The tool permission a cancelled run parked on is not served either.

        The durable row survives the cancellation, which is why the run is
        reported as holding permission residue; residue is an operator signal,
        never an offer to answer.
        """
        app, _hub, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            thread_id = _start_run(client, "terminal-disclosure-permission")
            request_id = asyncio.run(
                park_journaled_permission(
                    checkpointer,
                    session_factory,
                    thread_id=thread_id,
                    options=_ALLOW_ONCE_OFFER,
                )
            )
            assert request_id
            asyncio.run(_cancel(session_factory, thread_id))

            status = client.get(f"/v1/runs/{thread_id}")
            history = client.get(f"/v1/runs/{thread_id}/history")

        assert status.status_code == 200, status.text
        status_body = status.json()
        assert status_body["status"] == ThreadStatus.CANCELLED.value
        assert status_body["approval_status"] is None
        assert status_body["approval_request_id"] is None
        assert status_body["topology"]["pause_cause"] is None

        assert history.status_code == 200, history.text
        state = history.json()["state"]
        assert state["pending_permissions"] == []
        assert state["pause_cause"] is None
