"""Endpoint proofs that DELETE resumes one durable saga under replay.

A lost response makes a client resend DELETE, and a crash can leave a teardown
half-done. The endpoint must converge on one deletion either way: a replay of a
finished delete is idempotent, and a request that arrives while a saga is still
mid-flight rejoins that same saga and finishes it rather than starting a second
teardown.

These drive the real DELETE route against a real SQLite database and a real
AsyncSqliteSaver checkpoint store - no mocks - through the FastAPI test client.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint

from vaultspec_a2a.control.repositories import (
    CleanupItem,
    CleanupKind,
    create_deletion_saga,
)
from vaultspec_a2a.database import create_thread, get_thread
from vaultspec_a2a.database.models import ThreadDeletionSagaModel

from .conftest import make_app


class TestDeletionSagaEndpoint:
    """DELETE /api/threads/{id} under replay and mid-flight resume."""

    def test_replayed_delete_after_completion_is_idempotent(
        self, session_factory, checkpointer
    ) -> None:
        """A second DELETE of an already-deleted thread reports it gone."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> None:
            await checkpointer.setup()
            async with session_factory() as session:
                await create_thread(session, thread_id="t-replay", status="completed")
                await session.commit()

        asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            first = client.delete("/api/threads/t-replay")
            second = client.delete("/api/threads/t-replay")

        assert first.status_code == 204
        assert second.status_code == 404

    def test_delete_resumes_a_mid_flight_saga(
        self, session_factory, checkpointer
    ) -> None:
        """A DELETE on an already-deleting thread finishes the existing saga.

        The saga is seeded with its checkpoint item outstanding, as a crashed
        first pass would leave it. The endpoint must resume that saga, remove
        the checkpoint, and finalize - not start a second teardown.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> None:
            await checkpointer.setup()
            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-resume"
            await checkpointer.aput(
                {"configurable": {"thread_id": "t-resume", "checkpoint_ns": ""}},
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {},
            )
            async with session_factory() as session:
                await create_thread(session, thread_id="t-resume", status="completed")
                await create_deletion_saga(
                    session,
                    thread_id="t-resume",
                    manifest=[
                        CleanupItem(
                            kind=CleanupKind.CHECKPOINT,
                            key="checkpoint",
                            target="t-resume",
                        )
                    ],
                )
                await session.commit()

        async def _checkpoint_exists() -> bool:
            config = {"configurable": {"thread_id": "t-resume", "checkpoint_ns": ""}}
            return await checkpointer.aget_tuple(config) is not None

        async def _rows_gone() -> tuple[bool, bool]:
            async with session_factory() as session:
                thread = await get_thread(session, "t-resume")
                saga = await session.get(ThreadDeletionSagaModel, "t-resume")
                return thread is None, saga is None

        asyncio.run(_seed())
        assert asyncio.run(_checkpoint_exists()) is True

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.delete("/api/threads/t-resume")

        assert resp.status_code == 204
        assert asyncio.run(_checkpoint_exists()) is False
        thread_gone, saga_gone = asyncio.run(_rows_gone())
        assert thread_gone is True
        assert saga_gone is True
