"""Ordinary gateway boot must not rewrite the checkpoint store.

The boot sequence ran the SDD backfill on every non-armed start with a SQLite
checkpoint backend, decoding and re-encoding every checkpoint row in the store.
It repaired nothing any reader can see: a checkpoint written before those
channels existed resumes, and every production reader treats them as optional,
so the served state is identical with and without the rewrite. The one profile
that does require the repair - the desktop one, whose ordinary boot refuses to
start while a row is pending - gets it from its own staged-generation migration
entrypoint, not from here.

Both halves are proved against a real store: boot leaves legacy rows byte for
byte as it found them, and the migration entrypoint's repair still works.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ...api.app import _initialize_gateway_database
from ...testing import settings_override
from ...thread.state import TeamState
from .. import close_db
from ..migrations import backfill_teamstate_sdd_fields, count_pending_sdd_backfill

if TYPE_CHECKING:
    from pathlib import Path

_SDD_CHANNELS = ("active_feature", "pipeline_phase", "vault_index", "validation_errors")


def _graph(saver: Any) -> Any:
    async def answer(state: TeamState) -> dict[str, Any]:
        del state
        return {"messages": [AIMessage(content="answered")]}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))
    builder.add_node("answer", answer)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile(checkpointer=saver)


def _legacy_input(thread_id: str) -> dict[str, Any]:
    """A first-ingest input as it was before the SDD channels were threaded."""
    return {
        "messages": [HumanMessage(content="go")],
        "thread_id": thread_id,
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "active_agent": "",
    }


async def _write_legacy_thread(checkpoint_db: Path, thread_id: str) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db)) as saver:
        await saver.setup()
        await _graph(saver).ainvoke(
            cast("Any", _legacy_input(thread_id)),
            cast("Any", {"configurable": {"thread_id": thread_id}}),
        )


def _checkpoint_blobs(checkpoint_db: Path) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(str(checkpoint_db))
    try:
        return list(
            connection.execute(
                "SELECT checkpoint_id, type, checkpoint FROM checkpoints "
                "ORDER BY checkpoint_id"
            )
        )
    finally:
        connection.close()


async def _served_state(checkpoint_db: Path, thread_id: str) -> dict[str, Any]:
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db)) as saver:
        state = await _graph(saver).aget_state(
            cast("Any", {"configurable": {"thread_id": thread_id}})
        )
    # The read shape every production consumer of these channels uses.
    return {
        "active_feature": state.values.get("active_feature"),
        "pipeline_phase": state.values.get("pipeline_phase"),
        "vault_index": state.values.get("vault_index") or {},
        "validation_errors": state.values.get("validation_errors") or [],
    }


@pytest.mark.asyncio
async def test_boot_does_not_rewrite_legacy_checkpoint_rows(tmp_path: Path) -> None:
    """A store full of legacy rows comes out of boot exactly as it went in."""
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    thread_id = "legacy-boot"
    await _write_legacy_thread(checkpoint_db, thread_id)
    before = _checkpoint_blobs(checkpoint_db)
    assert before, "the store must hold checkpoints for this to prove anything"
    # The premise: this store is exactly what the retired boot step targeted.
    # Not every row qualifies - LangGraph's input-staging checkpoint carries no
    # TeamState - so the pending count is the number to hold steady.
    pending = count_pending_sdd_backfill(checkpoint_db)
    assert pending > 0

    # Boot seats the process-wide engine; another test's seat would refuse it,
    # and leaving this one seated would refuse the next test's.
    await close_db()
    try:
        with settings_override(
            database_backend="sqlite",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'app.db'}",
            checkpoint_backend="sqlite",
            checkpoint_database_url=f"sqlite+aiosqlite:///{checkpoint_db}",
        ):
            await _initialize_gateway_database(FastAPI(), armed=False)
    finally:
        await close_db()

    assert _checkpoint_blobs(checkpoint_db) == before
    assert count_pending_sdd_backfill(checkpoint_db) == pending


@pytest.mark.asyncio
async def test_a_legacy_thread_serves_the_same_state_either_way(
    tmp_path: Path,
) -> None:
    """Which is why boot has no reason to rewrite it.

    The channels are absent from the checkpoint and every reader treats them as
    optional, so the repair changes the bytes and nothing else. If this ever
    stops holding, the retired boot step was load-bearing after all.
    """
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    thread_id = "legacy-read"
    await _write_legacy_thread(checkpoint_db, thread_id)
    stored = _checkpoint_blobs(checkpoint_db)
    pending = count_pending_sdd_backfill(checkpoint_db)
    assert pending > 0

    before = await _served_state(checkpoint_db, thread_id)

    assert backfill_teamstate_sdd_fields(checkpoint_db) == pending
    assert _checkpoint_blobs(checkpoint_db) != stored, "the repair rewrote the rows"

    assert await _served_state(checkpoint_db, thread_id) == before


@pytest.mark.asyncio
async def test_the_migration_entrypoint_still_repairs_what_armed_boot_requires(
    tmp_path: Path,
) -> None:
    """Armed boot refuses on a pending row, so the staged path must clear them."""
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    await _write_legacy_thread(checkpoint_db, "legacy-armed")
    assert count_pending_sdd_backfill(checkpoint_db) > 0

    backfill_teamstate_sdd_fields(checkpoint_db)

    assert count_pending_sdd_backfill(checkpoint_db) == 0
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db)) as saver:
        latest = await saver.aget_tuple(
            cast("Any", {"configurable": {"thread_id": "legacy-armed"}})
        )
    assert latest is not None
    assert all(
        channel in latest.checkpoint["channel_values"] for channel in _SDD_CHANNELS
    )
