"""The gateway prunes a run's checkpoint history once its terminal is proven.

Drives the real relay seam (``_handle_terminal_event``) against a real SQLite
application database and a real checkpoint store holding a superseded
checkpoint beneath the run's proven completion. Pruning follows acceptance and
never precedes it: a completion the checkpoint cannot prove keeps every
checkpoint recovery may still need.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
from langgraph.graph import END, START

from ...control.accepted_input import freeze_accepted_input
from ...database import ThreadModel, create_control_action, create_thread
from ...graph.nodes._worker_permissions import (
    permission_callback_for,
    recorded_permission_answers,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...testing import (
    DEFAULT_TEAM_PRESET,
    add_test_node,
    compile_test_graph,
    new_state_graph,
    seed_completed_authority,
)
from ...tests._checkpoint_seeding import real_checkpoint
from ...thread import RunWriteAuthority
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.idempotency import thread_create_action_key
from ...thread.state import TeamState
from ..dispatch_receipts import prepare_graph_action_receipt
from ..event_handlers import (
    CheckpointPruneRegistry,
    RelayServices,
    _handle_terminal_event,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
    )


async def _put_bare_checkpoint(
    checkpointer: AsyncSqliteSaver, thread_id: str, checkpoint_id: str
) -> None:
    checkpoint = await real_checkpoint()
    checkpoint["id"] = checkpoint_id
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 0, "parents": {}},
        {},
    )


async def _checkpoint_ids(checkpointer: AsyncSqliteSaver, thread_id: str) -> list[str]:
    config = cast("Any", {"configurable": {"thread_id": thread_id}})
    return sorted(
        [
            cast("Mapping[str, Mapping[str, str]]", item.config)["configurable"][
                "checkpoint_id"
            ]
            async for item in checkpointer.alist(config)
        ]
    )


async def _status(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> str:
    async with session_factory() as session:
        row = await session.get(ThreadModel, thread_id)
    assert row is not None
    return row.status


@pytest.mark.asyncio
async def test_a_proven_completion_prunes_the_superseded_checkpoints(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with session_factory() as session:
        thread_id, _receipt = await seed_completed_authority(
            session, checkpointer, title="settled history"
        )
    # Sorts beneath the seeded completion, as an earlier superstep's id would.
    await _put_bare_checkpoint(checkpointer, thread_id, f"a-{thread_id}")
    assert await _checkpoint_ids(checkpointer, thread_id) == [
        f"a-{thread_id}",
        f"cp-{thread_id}",
    ]

    prunes = CheckpointPruneRegistry()
    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        services=RelayServices(
            session_factory=session_factory,
            checkpointer=checkpointer,
            prune_registry=prunes,
        ),
    )
    # The prune runs behind the relay rather than inside it; shutdown waits for
    # it the same way before closing the store.
    await prunes.settle()

    assert await _status(session_factory, thread_id) == ThreadStatus.COMPLETED
    assert await _checkpoint_ids(checkpointer, thread_id) == [f"cp-{thread_id}"]


@pytest.mark.asyncio
async def test_an_unproven_completion_keeps_the_whole_history(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with session_factory() as session:
        thread_id, _receipt = await seed_completed_authority(
            session, checkpointer, title="unproven history"
        )
    # A newer checkpoint carrying no completion receipt is what the proof reads,
    # so the completion is refused and the run is not settled.
    await _put_bare_checkpoint(checkpointer, thread_id, f"a-{thread_id}")
    await _put_bare_checkpoint(checkpointer, thread_id, f"zz-{thread_id}")
    history = await _checkpoint_ids(checkpointer, thread_id)
    assert len(history) == 3

    prunes = CheckpointPruneRegistry()
    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        services=RelayServices(
            session_factory=session_factory,
            checkpointer=checkpointer,
            prune_registry=prunes,
        ),
    )
    await prunes.settle()

    assert await _status(session_factory, thread_id) != ThreadStatus.COMPLETED
    assert await _checkpoint_ids(checkpointer, thread_id) == history


# ---------------------------------------------------------------------------
# R4 T7: a parked interrupt survives a stray completed terminal.
# ---------------------------------------------------------------------------

#: What a provider offers for one tool call: a once-only approval and refusal.
_TOOL_OPTIONS: list[dict[str, Any]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


def _asking(
    tool_name: str, tool_input: dict[str, Any], offered: list[dict[str, Any]]
) -> Any:
    """A node that asks for one tool call through the worker's own callback.

    The callback raises the real ``GraphInterrupt`` LangGraph parks a task on,
    so the checkpoint this leaves holds a genuine unanswered interrupt write -
    not a stand-in for one.
    """

    async def ask(state: TeamState) -> dict[str, Any]:
        callback = permission_callback_for(recorded_permission_answers(state))
        await callback(tool_name, tool_input, offered)
        return {}

    return ask


def _parked_interrupt_graph(checkpointer: AsyncSqliteSaver) -> Any:
    """A one-node graph that parks on a tool permission every time it runs."""
    builder = new_state_graph(TeamState)
    add_test_node(builder, "ask", _asking("bash", {"command": "ls"}, _TOOL_OPTIONS))
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    return compile_test_graph(
        builder, checkpointer=checkpointer, name="parked-interrupt-probe"
    )


@pytest.mark.asyncio
async def test_a_stray_completed_terminal_does_not_settle_a_parked_run(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A run parked on an unanswered interrupt ignores a stray completion terminal.

    Completion is proven off the checkpoint, never taken on the event's own
    say-so. A checkpoint still holding an unanswered interrupt write classifies
    as ``checkpoint_interrupted``, never ``checkpoint_completed`` (R4 T7), so the
    stray terminal below is refused: the run keeps its parked status, and its
    checkpoint - carrying the interrupt it is parked on - is never pruned.
    """
    thread_id = "parked-interrupt-run"
    async with session_factory() as session:
        await create_thread(
            session,
            thread_id=thread_id,
            status=ThreadStatus.INPUT_REQUIRED,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, "accepted"
            ),
        )
        await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.INGEST,
            idempotency_key=thread_create_action_key(thread_id),
            dispatch_id="accepted",
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            payload=freeze_accepted_input(
                DispatchRequest(
                    action="ingest",
                    thread_id=thread_id,
                    content="work",
                    workspace_root=str(tmp_path),
                    recursion_limit=25,
                    team_preset=DEFAULT_TEAM_PRESET,
                    graph_definition=freeze_graph_definition(
                        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=tmp_path),
                        workspace_root=tmp_path,
                    ),
                ),
                intent={"content": "work"},
            ),
        )
        receipt = await prepare_graph_action_receipt(
            session, thread_id=thread_id, dispatch_id="accepted"
        )
        assert receipt is not None
        await session.commit()

    config = cast("Any", {"configurable": {"thread_id": thread_id}})
    await _parked_interrupt_graph(checkpointer).ainvoke(
        {
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
            "graph_action_receipts": {
                receipt.dispatch_id: receipt.model_dump(mode="json")
            },
        },
        config,
    )
    parked = await checkpointer.aget_tuple(config)
    assert parked is not None
    assert parked.pending_writes, "the ask node must leave an unanswered interrupt"
    history_before = await _checkpoint_ids(checkpointer, thread_id)

    prunes = CheckpointPruneRegistry()
    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        services=RelayServices(
            session_factory=session_factory,
            checkpointer=checkpointer,
            prune_registry=prunes,
        ),
    )
    await prunes.settle()

    assert await _status(session_factory, thread_id) == ThreadStatus.INPUT_REQUIRED
    assert await _checkpoint_ids(checkpointer, thread_id) == history_before
