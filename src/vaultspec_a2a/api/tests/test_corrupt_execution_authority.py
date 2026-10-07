"""A run whose stored execution authority is corrupt is READ, not refused.

The frozen team selection in a run's metadata is digest-protected, so a stored
record whose digest no longer matches is rejected by the validator. The capture
has always degraded over that - it reports
``incompatible_execution_authority`` and serves the rest of the record - while
the run-status route read the same bytes a second time and let the validation
error out as a 500. The two readings of one field disagreed, and the louder one
cost the caller every other field of a run it most needed to inspect.

Driven over the real route with a real store row, because the shape under test is
the response code.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...testing import current_execution_metadata, seed_journaled_thread
from ...thread.enums import DegradedReason, ThreadStatus
from .conftest import make_app

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


type SessionFactory = async_sessionmaker[AsyncSession]

#: A well-formed digest that is not the one the stored selection hashes to, so
#: the record fails on its integrity check rather than on its shape: the shape
#: is the part a reader could not have repaired anyway.
_WRONG_DIGEST = "0" * 64


def _metadata_with_corrupt_selection() -> str:
    """Serialize run metadata whose frozen selection fails its digest check."""
    decoded = cast("dict[str, Any]", json.loads(current_execution_metadata(Path.cwd())))
    selection = cast("dict[str, Any]", decoded["provider_catalog_selection"])
    selection["digest"] = _WRONG_DIGEST
    return json.dumps(decoded)


async def _seed_corrupt_run(session_factory: SessionFactory, thread_id: str) -> None:
    """Commit a journaled run carrying the corrupt authority in its metadata."""
    async with session_factory() as session:
        await seed_journaled_thread(
            session,
            status=ThreadStatus.RUNNING,
            thread_id=thread_id,
            metadata=_metadata_with_corrupt_selection(),
        )
        await session.commit()


def test_run_status_degrades_a_corrupt_frozen_selection(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Run-status answers 200 with the typed degraded reason, never 500."""
    asyncio.run(_seed_corrupt_run(session_factory, "corrupt-authority"))
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer)

    with TestClient(app, raise_server_exceptions=True) as client:
        status = client.get("/v1/runs/corrupt-authority")
        history = client.get("/v1/runs/corrupt-authority/history")

    assert status.status_code == 200, status.text
    body = status.json()
    assert body["frozen_assignment"] is None
    assert (
        DegradedReason.INCOMPATIBLE_EXECUTION_AUTHORITY.value
        in body["degraded_reasons"]
    )

    # The wide read already answered 200; it must keep agreeing with run-status
    # about why, so the two never report a different fault for one record.
    assert history.status_code == 200, history.text
    assert (
        DegradedReason.INCOMPATIBLE_EXECUTION_AUTHORITY.value
        in history.json()["state"]["degraded_reasons"]
    )
