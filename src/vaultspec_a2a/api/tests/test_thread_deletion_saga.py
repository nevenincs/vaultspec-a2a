"""Endpoint proofs of the DELETE contract's five distinct outcomes.

A lost response makes a client resend DELETE, and a crash can leave a teardown
half-done. The endpoint must converge on one deletion either way: a replay of a
finished delete is idempotent, and a request that arrives while a saga is still
mid-flight rejoins that same saga and finishes it rather than starting a second
teardown.

The saga also distinguishes more states than a two-code surface can carry, and
each one reaches the wire differently: a lifecycle refusal before the saga
begins is a conflict, a clean deletion is no-content, resumable incomplete
cleanup is retryable, an absent thread is not-found, and a deletion that
finalized over permanently unremovable state is a success carrying a body that
names the kinds of state left stranded.

These drive the real DELETE route against a real SQLite database and a real
AsyncSqliteSaver checkpoint store - no mocks - through the FastAPI test client.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.repositories import (
    CleanupItem,
    create_deletion_saga,
)
from ...database import create_artifact, create_thread, get_thread
from ...database.models import ThreadDeletionSagaModel
from ...thread.enums import CleanupKind
from .conftest import make_app

if TYPE_CHECKING:
    import pathlib


def _detached_checkpoint_store(db_file: pathlib.Path) -> AsyncSqliteSaver:
    """Return a real checkpoint store that can no longer serve a delete.

    Not a stub and not a patched object: this is a real ``AsyncSqliteSaver``
    over a real database file whose connection has been closed, which is the
    state a gateway is left holding when its checkpoint store goes away
    underneath it - a detached volume, a store that will not come back. Every
    cleanup pass against it fails for real, and after the saga's attempt
    ceiling the checkpoint item is abandoned rather than retried forever.
    """

    async def _build() -> AsyncSqliteSaver:
        async with AsyncSqliteSaver.from_conn_string(str(db_file)) as saver:
            await saver.setup()
            return saver

    saver = asyncio.run(_build())

    async def _confirm_detached() -> str:
        # Assert the premise rather than inferring it from the refusal sequence
        # the callers observe. If a library change ever made this store usable
        # again, those callers would see a clean deletion and assert the wrong
        # outcome for a plausible-looking reason; failing here instead points at
        # the cause. The delete must fail, and it must fail because the
        # connection is gone rather than because the thread is unknown.
        try:
            await saver.adelete_thread("premise-probe")
        except Exception as exc:
            # The message IS the assertion; the caller checks it names the
            # connection rather than a missing thread.
            return str(exc)
        return ""

    reason = asyncio.run(_confirm_detached())
    assert "connection" in reason.lower(), (
        f"the detached store still served a delete ({reason!r}); the abandonment "
        f"tests below would then prove nothing"
    )
    return saver


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

    def test_a_lifecycle_refusal_is_a_conflict_and_starts_no_saga(
        self, session_factory, checkpointer
    ) -> None:
        """A thread whose state refuses deletion is rejected before any teardown.

        This outcome is not a saga state at all: nothing durable is written and
        no external effect is attempted, so the thread must still be there
        afterwards with no saga row beside it.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> None:
            await checkpointer.setup()
            async with session_factory() as session:
                await create_thread(session, thread_id="t-running", status="running")
                await session.commit()

        async def _survives() -> tuple[bool, bool]:
            async with session_factory() as session:
                thread = await get_thread(session, "t-running")
                saga = await session.get(ThreadDeletionSagaModel, "t-running")
                return thread is not None, saga is None

        asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.delete("/api/threads/t-running")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Cannot delete thread in 'running' state"
        thread_present, no_saga = asyncio.run(_survives())
        assert thread_present is True
        assert no_saga is True

    def test_a_delete_stranding_checkpoint_state_succeeds_and_says_so(
        self, session_factory, tmp_path
    ) -> None:
        """An unremovable checkpoint yields retries, then a success naming it.

        Nothing here is arranged after the fact: the manifest is captured by the
        production path from the thread's own artifacts, the artifact file is
        really unlinked, and the checkpoint item really fails against a detached
        store on every pass. The first two requests are retryable because a
        retry can still make progress; the third finalizes over the item the
        saga has stopped retrying, and reports the kind it left behind. The
        cleaned artifact kind is absent from that report - only stranded state
        is named.
        """
        store = _detached_checkpoint_store(tmp_path / "detached_checkpoints.db")
        app, _agg, _worker, _cp = make_app(session_factory, store)
        workspace = tmp_path / "workspace"
        (workspace / "outputs").mkdir(parents=True)
        artifact_file = workspace / "outputs" / "report.md"
        artifact_file.write_text("body", encoding="utf-8")

        async def _seed() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="t-strand",
                    status="completed",
                    metadata=json.dumps({"workspace_root": workspace.as_posix()}),
                )
                await create_artifact(
                    session,
                    thread_id="t-strand",
                    artifact_type="file",
                    path="outputs/report.md",
                )
                await session.commit()

        asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            responses = [client.delete("/api/threads/t-strand") for _ in range(3)]
            # The rows are gone, so the retry this outcome does NOT invite finds
            # nothing - which is exactly why abandonment is not service-unavailable.
            replay = client.delete("/api/threads/t-strand")

        assert [resp.status_code for resp in responses] == [503, 503, 200]
        assert responses[-1].json() == {
            "api_version": "v1",
            "thread_id": "t-strand",
            "deleted": True,
            "cleanup_abandoned": True,
            "abandoned_kinds": [CleanupKind.CHECKPOINT.value],
        }
        assert artifact_file.exists() is False
        assert replay.status_code == 404

    def test_the_abandonment_body_names_every_stranded_kind(
        self, session_factory, tmp_path
    ) -> None:
        """Both stranded kinds are named, in the cleanup manifest's own order.

        The artifact item here can never be cleaned: it was captured against a
        workspace root its target does not sit under, so every pass refuses it
        as an escaping path rather than removing a file the thread does not own.
        Paired with a detached checkpoint store, the delete finalizes over two
        different kinds of stranded state and has to name both.
        """
        store = _detached_checkpoint_store(tmp_path / "detached_checkpoints.db")
        app, _agg, _worker, _cp = make_app(session_factory, store)

        async def _seed() -> None:
            async with session_factory() as session:
                await create_thread(session, thread_id="t-both", status="completed")
                await create_deletion_saga(
                    session,
                    thread_id="t-both",
                    manifest=[
                        CleanupItem(
                            kind=CleanupKind.CHECKPOINT,
                            key="checkpoint",
                            target="t-both",
                        ),
                        CleanupItem(
                            kind=CleanupKind.ARTIFACT_FILE,
                            key="artifact:gone",
                            target="/elsewhere/out/report.md",
                            root="/workspace",
                        ),
                    ],
                )
                await session.commit()

        asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            responses = [client.delete("/api/threads/t-both") for _ in range(3)]

        assert [resp.status_code for resp in responses] == [503, 503, 200]
        assert responses[-1].json()["abandoned_kinds"] == [
            CleanupKind.CHECKPOINT.value,
            CleanupKind.ARTIFACT_FILE.value,
        ]
        # No filesystem path, ledger key, or failure detail reaches the caller.
        serialized = responses[-1].text
        assert "elsewhere" not in serialized
        assert "artifact:gone" not in serialized
