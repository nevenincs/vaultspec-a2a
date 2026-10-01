"""Real durable state for the continuation suites: one busy run and a queue.

Everything here builds production objects through production verbs - a real
SQLite application database at the packaged schema, a real frozen graph
definition, a real accepted dispatch envelope, a real journal reservation
through the queue repository, and a real LangGraph run over a real
``AsyncSqliteSaver`` for the completion receipt. The suites that import it
assert on what those produce.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import (
    create_control_action,
    create_thread,
    get_control_action_by_dispatch_id,
)
from ...database.models import Base, ControlActionModel, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...graph.compiler import CompiledTeamGraph, _add_node, _compile_graph
from ...graph.nodes.action_completion import (
    GRAPH_COMPLETION_NODE,
    record_graph_completion,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ...thread.state import TeamState
from ..accepted_input import freeze_accepted_input
from ..dispatch_receipts import prepare_graph_action_receipt
from ..repositories import (
    ContinuationQueueLimits,
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    reserve_queued_continuation,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ...thread.action_receipts import GraphActionReceipt

RUN = "promotion-run"
PRESET = "mock-success-single"
FIRST_RECEIPT = "first-turn-dispatch"
ROOMY = ContinuationQueueLimits(per_run_depth=3, service_cap=9)


@dataclass(frozen=True, slots=True)
class BusyRun:
    """A RUNNING run whose first turn is accepted, receipted and provable."""

    sessions: async_sessionmaker[AsyncSession]
    saver: AsyncSqliteSaver
    receipt: GraphActionReceipt
    workspace: Path


def definition(workspace: Path) -> FrozenGraphDefinition:
    """Freeze the real team the continuation suites run."""
    return freeze_graph_definition(
        load_team_config(PRESET, workspace_root=workspace),
        workspace_root=workspace,
    )


def envelope(content: str, workspace: Path) -> dict[str, object]:
    """Freeze the complete accepted dispatch input one turn is rebuilt from."""
    return freeze_accepted_input(
        DispatchRequest(
            action="ingest",
            thread_id=RUN,
            agent_id="vaultspec-supervisor",
            content=content,
            workspace_root=str(workspace),
            team_preset=PRESET,
            graph_definition=definition(workspace),
            recursion_limit=37,
        ),
        intent={"content": content, "agent_id": "vaultspec-supervisor"},
    )


@asynccontextmanager
async def busy_run_state(
    tmp_path: Path, *, created_at: datetime | None = None
) -> AsyncGenerator[BusyRun]:
    """Open a real application database holding one run mid-first-turn.

    *created_at* backdates the run's own creation, which is the only way to
    reach the total-lifetime bound without waiting a day for it.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        thread = await create_thread(
            db,
            thread_id=RUN,
            status=ThreadStatus.RUNNING,
            team_preset=PRESET,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, FIRST_RECEIPT
            ),
        )
        if created_at is not None:
            thread.created_at = created_at
        await create_control_action(
            db,
            thread_id=RUN,
            action_type=ControlActionType.INGEST,
            idempotency_key=f"thread-create:{RUN}",
            dispatch_id=FIRST_RECEIPT,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=30),
            payload=envelope("first turn", tmp_path),
        )
        receipt = await prepare_graph_action_receipt(
            db, thread_id=RUN, dispatch_id=FIRST_RECEIPT
        )
        if receipt is None:
            raise RuntimeError("the seeded first turn could not take a receipt")
        await db.commit()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.db")) as saver:
        yield BusyRun(sessions, saver, receipt, tmp_path)
    await engine.dispose()


def _work(_state: TeamState) -> dict[str, object]:
    return {}


def probe_graph(saver: AsyncSqliteSaver) -> CompiledTeamGraph:
    """Compile the smallest real graph that records a completion receipt."""
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))
    _add_node(builder, "work", _work)
    _add_node(builder, GRAPH_COMPLETION_NODE, record_graph_completion)
    builder.add_edge(START, "work")
    builder.add_edge("work", GRAPH_COMPLETION_NODE)
    builder.add_edge(GRAPH_COMPLETION_NODE, END)
    return _compile_graph(
        builder, checkpointer=saver, interrupt_before=[], name="continuation-probe"
    )


async def finish_turn(saver: AsyncSqliteSaver, receipt: GraphActionReceipt) -> None:
    """Run the real graph so the checkpoint proves this turn completed."""
    config: RunnableConfig = {"configurable": {"thread_id": RUN}}
    await probe_graph(saver).ainvoke(
        {
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
            "graph_action_receipts": {
                receipt.dispatch_id: receipt.model_dump(mode="json")
            },
        },
        config,
    )


async def queue_continuation(
    sessions: async_sessionmaker[AsyncSession],
    workspace: Path,
    *,
    key: str = "second-turn",
    content: str = "second turn",
    lifetime_deadline_at: datetime | None = None,
) -> str:
    """Admit one continuation through the production queue repository."""
    async with sessions() as db:
        outcome = await reserve_queued_continuation(
            db,
            QueuedContinuationRequest(
                thread_id=RUN,
                idempotency_key=key,
                payload=envelope(content, workspace),
                dispatch_id=f"dispatch-{key}",
                lifetime_deadline_at=(
                    lifetime_deadline_at or datetime.now(UTC) + timedelta(hours=6)
                ),
                limits=ROOMY,
            ),
        )
        await db.commit()
    if outcome.disposition is not QueuedContinuationDisposition.QUEUED:
        raise RuntimeError(f"the continuation was not admitted: {outcome.disposition}")
    return outcome.dispatch_id


async def checkpoint_count(saver: AsyncSqliteSaver) -> int:
    """Count the checkpoints this run's history still holds."""
    config: RunnableConfig = {"configurable": {"thread_id": RUN}}
    return len([stored async for stored in saver.alist(config)])


async def journal_action(session: AsyncSession, dispatch_id: str) -> ControlActionModel:
    """Read one journal row by its stable dispatch identity."""
    action = await get_control_action_by_dispatch_id(
        session, thread_id=RUN, dispatch_id=dispatch_id
    )
    if action is None:
        raise RuntimeError(f"no journal action carries dispatch {dispatch_id}")
    return action
