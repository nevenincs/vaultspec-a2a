"""Both readings of a failed run disclose its provider condition as the enum.

The condition is the machine-readable half of a failure: it says what the reader
should DO - wait, re-authenticate, top up, raise a ceiling, change the request -
so a client branches on a member instead of matching vendor prose. That promise is
only checkable if the field is served as its enumeration, and the run read model
served a bare string because the vocabulary sat outside Layer 1.

Driven over the real routes against a real store row elected to failed by the
production election, so the value crosses the durable column the way a failure
writes it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...graph.enums import ProviderCondition
from ...testing import elect_status, seed_accepted_thread
from ...thread.enums import ThreadStatus
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


type SessionFactory = async_sessionmaker[AsyncSession]

_WORKSPACE = Path(__file__).resolve().parent


async def _seed_failed_run(
    session_factory: SessionFactory, thread_id: str, condition: ProviderCondition
) -> None:
    """Commit a run the election failed, carrying *condition* on its row."""
    async with session_factory() as session:
        await seed_accepted_thread(session, thread_id=thread_id, workspace=_WORKSPACE)
        await elect_status(
            session,
            thread_id,
            ThreadStatus.FAILED,
            failure_reason="the lane refused for rate",
            provider_condition=condition.value,
        )
        await session.commit()


def test_both_readings_serve_the_stored_provider_condition(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Run-status and run-history agree, and both answer with a member."""
    asyncio.run(
        _seed_failed_run(session_factory, "condition-run", ProviderCondition.THROTTLED)
    )
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)

    with TestClient(app, raise_server_exceptions=True) as client:
        status = client.get("/v1/runs/condition-run")
        history = client.get("/v1/runs/condition-run/history")

    assert status.status_code == 200, status.text
    assert history.status_code == 200, history.text
    served = ProviderCondition.THROTTLED.value
    assert status.json()["provider_condition"] == served
    assert history.json()["state"]["provider_condition"] == served


def test_the_published_read_model_names_the_condition_enumeration(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The wide read publishes the vocabulary, not an unconstrained string.

    A bare string published the field without the closed set a client branches
    on, so a generated client had no type to switch over and no way to tell a
    member it did not know from a message it should not parse.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)
    schemas = app.openapi()["components"]["schemas"]

    published = schemas["ThreadStateSnapshot"]["properties"]["provider_condition"]

    assert {"$ref": "#/components/schemas/ProviderCondition"} in published["anyOf"], (
        published
    )
    assert set(schemas["ProviderCondition"]["enum"]) == {
        member.value for member in ProviderCondition
    }
