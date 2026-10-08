"""Real durable state for the continuation suites: one busy run and a queue.

Everything here builds production objects through production verbs - a real
frozen graph definition, a real accepted dispatch envelope, a real journal
reservation through the continuation queue, and a real LangGraph run over a real
``AsyncSqliteSaver`` for the completion receipt - inside the root
``migrated_session_factory`` and ``checkpointer`` stores the suite hands in. The
suites that import it assert on what those produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from langgraph.graph import END, START

from ...database import (
    create_control_action,
    create_thread,
    get_control_action_by_dispatch_id,
)
from ...graph.nodes.action_completion import (
    GRAPH_COMPLETION_NODE,
    record_graph_completion,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...testing import (
    DEFAULT_TEAM_PRESET,
    add_test_node,
    compile_test_graph,
    new_state_graph,
)
from ...thread import RunWriteAuthority
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ...thread.idempotency import thread_create_action_key
from ...thread.state import TeamState
from ..accepted_input import freeze_accepted_input
from ..continuation_queue import (
    ContinuationQueueLimits,
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    reserve_queued_continuation,
)
from ..dispatch_receipts import prepare_graph_action_receipt

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...database import ControlActionModel
    from ...graph.compiler import CompiledTeamGraph
    from ...thread.action_receipts import GraphActionReceipt

__all__ = [
    "FIRST_RECEIPT",
    "RUN",
    "BusyRun",
    "checkpoint_count",
    "definition",
    "envelope",
    "finish_turn",
    "journal_action",
    "queue_continuation",
    "seed_busy_run",
    "start_busy_run",
]

RUN = "promotion-run"
FIRST_RECEIPT = "first-turn-dispatch"
_ROOMY = ContinuationQueueLimits(per_run_depth=3, service_cap=9)


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
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=workspace),
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
            team_preset=DEFAULT_TEAM_PRESET,
            graph_definition=definition(workspace),
            recursion_limit=37,
        ),
        intent={"content": content, "agent_id": "vaultspec-supervisor"},
    )


async def seed_busy_run(
    db: AsyncSession, workspace: Path, *, created_at: datetime | None = None
) -> GraphActionReceipt:
    """Write one run mid-first-turn into an already-open application database.

    Separate from :func:`start_busy_run` so a suite that owns its own stores -
    a live gateway's database and checkpointer - reaches the same run through
    the same production verbs rather than through a second description of it.

    *created_at* backdates the run's own creation, which is the only way to
    reach the total-lifetime bound without waiting a day for it.
    """
    thread = await create_thread(
        db,
        thread_id=RUN,
        status=ThreadStatus.RUNNING,
        team_preset=DEFAULT_TEAM_PRESET,
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
        idempotency_key=thread_create_action_key(RUN),
        dispatch_id=FIRST_RECEIPT,
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=30),
        payload=envelope("first turn", workspace),
    )
    receipt = await prepare_graph_action_receipt(
        db, thread_id=RUN, dispatch_id=FIRST_RECEIPT
    )
    if receipt is None:
        raise RuntimeError("the seeded first turn could not take a receipt")
    await db.commit()
    return receipt


async def start_busy_run(
    sessions: async_sessionmaker[AsyncSession],
    saver: AsyncSqliteSaver,
    workspace: Path,
    *,
    created_at: datetime | None = None,
) -> BusyRun:
    """Seed one run mid-first-turn into the stores a suite was handed.

    *created_at* backdates the run's own creation, which is the only way to
    reach the total-lifetime bound without waiting a day for it.
    """
    async with sessions() as db:
        receipt = await seed_busy_run(db, workspace, created_at=created_at)
    return BusyRun(sessions, saver, receipt, workspace)


def _work(_state: TeamState) -> dict[str, object]:
    return {}


def _probe_graph(saver: AsyncSqliteSaver) -> CompiledTeamGraph:
    """Compile the smallest real graph that records a completion receipt."""
    builder = new_state_graph(TeamState)
    add_test_node(builder, "work", _work)
    add_test_node(builder, GRAPH_COMPLETION_NODE, record_graph_completion)
    builder.add_edge(START, "work")
    builder.add_edge("work", GRAPH_COMPLETION_NODE)
    builder.add_edge(GRAPH_COMPLETION_NODE, END)
    return compile_test_graph(
        builder, checkpointer=saver, interrupt_before=[], name="continuation-probe"
    )


async def finish_turn(saver: AsyncSqliteSaver, receipt: GraphActionReceipt) -> None:
    """Run the real graph so the checkpoint proves this turn completed."""
    config: RunnableConfig = {"configurable": {"thread_id": RUN}}
    await _probe_graph(saver).ainvoke(
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
    """Admit one continuation through the production continuation queue."""
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
                limits=_ROOMY,
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
