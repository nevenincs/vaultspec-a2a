"""A settled run's prune belongs to the app that waits for it, and gets a floor.

Two properties of the gateway's shutdown are proved here against real apps and
a real checkpoint store.

The prune phase keeps a reserved floor. Skipping it when the shared shutdown
budget is spent saves the shutdown nothing: the prune already started keeps
deleting, through a checkpointer the lines after it close.

The pending prunes are the relaying app's own. Held as process state, one
app's shutdown waited on another app's deletes against a store it does not
close, and could not tell which of the pending work was its to wait for.

Each store is read back with the blocking SQLite driver: a read that awaits
would hand the loop to a prune that has not started yet and report its work as
though the phase had waited for it.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...lifecycle.shutdown import ShutdownDeadline
from ...tests._checkpoint_seeding import real_checkpoint
from ..app import _settle_checkpoint_prunes
from .conftest import make_app
from .test_internal import _record_completed_checkpoint, _seed_accepted_thread

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from fastapi import FastAPI
    from langchain_core.runnables import RunnableConfig
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    SessionFactory = async_sessionmaker[AsyncSession]


def _stored_checkpoint_ids(path: Path, thread_id: str) -> list[str]:
    """Read one thread's stored checkpoints without yielding the event loop."""
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchall()
    return sorted(str(row[0]) for row in rows)


async def _put_checkpoint(
    saver: AsyncSqliteSaver, thread_id: str, checkpoint_id: str
) -> None:
    checkpoint = await real_checkpoint()
    checkpoint["id"] = checkpoint_id
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""}
    }
    await saver.aput(
        config, checkpoint, {"source": "loop", "step": 0, "parents": {}}, {}
    )


async def _seed_superseded_history(saver: AsyncSqliteSaver, thread_id: str) -> None:
    """Leave a settled run with one superseded checkpoint beneath its last."""
    await _put_checkpoint(saver, thread_id, f"a-{thread_id}")
    await _put_checkpoint(saver, thread_id, f"cp-{thread_id}")


@pytest_asyncio.fixture
async def own_store(tmp_path: Path) -> AsyncIterator[tuple[AsyncSqliteSaver, Path]]:
    """A second real checkpoint store, for the app that is not shutting down."""
    path = tmp_path / "other-checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield saver, path


@pytest.mark.asyncio(loop_scope="function")
async def test_a_spent_shutdown_budget_still_waits_out_the_prune(
    session_factory: SessionFactory,
    own_store: tuple[AsyncSqliteSaver, Path],
) -> None:
    """The phase runs on its floor, so no delete outlives the checkpointer."""
    saver, path = own_store
    thread_id = "spent-budget-run"
    await _seed_superseded_history(saver, thread_id)
    app: FastAPI = make_app(session_factory, saver)[0]
    spent = ShutdownDeadline.start(0.0)
    assert spent.remaining() == 0.0

    app.state.checkpoint_prunes.schedule(thread_id, saver)
    await _settle_checkpoint_prunes(app, spent)

    assert _stored_checkpoint_ids(path, thread_id) == [f"cp-{thread_id}"], (
        "the phase returned with the prune still in flight, leaving it to "
        "delete through a checkpointer the shutdown closes next"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_one_apps_shutdown_leaves_another_apps_prune_to_its_owner(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    own_store: tuple[AsyncSqliteSaver, Path],
) -> None:
    """A shutting-down app waits for its own pending prunes and no others."""
    other_saver, other_path = own_store
    other_thread = "other-app-run"
    await _seed_superseded_history(other_saver, other_thread)

    shutting_down: FastAPI = make_app(session_factory, checkpointer)[0]
    other: FastAPI = make_app(session_factory, other_saver)[0]
    other.state.checkpoint_prunes.schedule(other_thread, other_saver)

    await shutting_down.state.checkpoint_prunes.settle()

    assert _stored_checkpoint_ids(other_path, other_thread) == [
        f"a-{other_thread}",
        f"cp-{other_thread}",
    ], "a shutting-down app adopted the pending prune of another app's store"

    # The owner's own wait is what completes it.
    await other.state.checkpoint_prunes.settle()
    assert _stored_checkpoint_ids(other_path, other_thread) == [f"cp-{other_thread}"]


@pytest.mark.asyncio(loop_scope="function")
async def test_a_relayed_terminal_prunes_through_the_relaying_apps_registry(
    session_factory: SessionFactory,
    own_store: tuple[AsyncSqliteSaver, Path],
) -> None:
    """The whole path: real relay, the app's registry, its shutdown phase."""
    saver, store = own_store
    app: FastAPI = make_app(session_factory, saver)[0]
    async with session_factory() as session:
        thread_id, receipt = await _seed_accepted_thread(session)
        await session.commit()
    await _record_completed_checkpoint(saver, receipt)
    await _put_checkpoint(saver, thread_id, f"a-{thread_id}")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        relayed = await client.post(
            "/internal/events/batch",
            json={
                "events": [
                    {
                        "thread_id": thread_id,
                        "payload": {
                            "event_type": "thread_terminal",
                            "status": "completed",
                        },
                    }
                ]
            },
        )
        assert relayed.status_code == 200

    await _settle_checkpoint_prunes(app, ShutdownDeadline.start(5.0))

    assert _stored_checkpoint_ids(store, thread_id) == [f"cp-{thread_id}"], (
        "the relayed terminal scheduled no prune the app's shutdown could wait for"
    )
