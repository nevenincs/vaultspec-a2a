"""A proven turn hands the run to the continuation waiting behind it.

Driven end to end against the real pieces: a real LangGraph run over a real
``AsyncSqliteSaver`` produces the completion receipt, a real journal row
reserved through the production queue repository is the continuation, and the
real reconciliation authority reads one and promotes the other. Nothing here
stands in for anything.

The run must come out of this still RUNNING, owned by the next turn, with the
turn that just ended recorded as applied - and with none of the things a
settlement does: no terminal election, no settled-history prune, no release of
the run's admission slot.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import create_control_action, create_thread, get_thread
from ...database.models import Base, ControlActionModel, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...graph.compiler import CompiledTeamGraph, _add_node, _compile_graph
from ...graph.nodes.action_completion import (
    GRAPH_COMPLETION_NODE,
    record_graph_completion,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ...thread.state import TeamState
from ..accepted_input import freeze_accepted_input
from ..dispatch_receipts import prepare_graph_action_receipt
from ..drain import DrainGate
from ..event_handlers import CheckpointPruneRegistry, relay_event
from ..recovery_authority import (
    CONTINUATION_PROMOTED,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..repositories import (
    ContinuationQueueLimits,
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    count_queued_continuations,
    reserve_queued_continuation,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ...thread.action_receipts import GraphActionReceipt

_RUN = "promotion-run"
_PRESET = "mock-success-single"
_FIRST_RECEIPT = "first-turn-dispatch"
_ROOMY = ContinuationQueueLimits(per_run_depth=3, service_cap=9)

type PromotionFixture = tuple[
    async_sessionmaker[AsyncSession], AsyncSqliteSaver, "GraphActionReceipt", "Path"
]


def _definition(workspace: Path) -> FrozenGraphDefinition:
    return freeze_graph_definition(
        load_team_config(_PRESET, workspace_root=workspace),
        workspace_root=workspace,
    )


def _envelope(content: str, workspace: Path) -> dict[str, object]:
    return freeze_accepted_input(
        DispatchRequest(
            action="ingest",
            thread_id=_RUN,
            agent_id="vaultspec-supervisor",
            content=content,
            workspace_root=str(workspace),
            team_preset=_PRESET,
            graph_definition=_definition(workspace),
            recursion_limit=37,
        ),
        intent={"content": content, "agent_id": "vaultspec-supervisor"},
    )


@pytest_asyncio.fixture
async def busy_run(tmp_path: Path) -> AsyncIterator[PromotionFixture]:
    """A RUNNING run whose first turn is accepted, receipted and dispatchable."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        await create_thread(
            db,
            thread_id=_RUN,
            status=ThreadStatus.RUNNING,
            team_preset=_PRESET,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, _FIRST_RECEIPT
            ),
        )
        await create_control_action(
            db,
            thread_id=_RUN,
            action_type=ControlActionType.INGEST,
            idempotency_key=f"thread-create:{_RUN}",
            dispatch_id=_FIRST_RECEIPT,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=30),
            payload=_envelope("first turn", tmp_path),
        )
        receipt = await prepare_graph_action_receipt(
            db, thread_id=_RUN, dispatch_id=_FIRST_RECEIPT
        )
        assert receipt is not None
        await db.commit()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.db")) as saver:
        yield sessions, saver, receipt, tmp_path
    await engine.dispose()


def _work(_state: TeamState) -> dict[str, object]:
    return {}


def _graph(saver: AsyncSqliteSaver) -> CompiledTeamGraph:
    """Compile the smallest real graph that records a completion receipt."""
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))
    _add_node(builder, "work", _work)
    _add_node(builder, GRAPH_COMPLETION_NODE, record_graph_completion)
    builder.add_edge(START, "work")
    builder.add_edge("work", GRAPH_COMPLETION_NODE)
    builder.add_edge(GRAPH_COMPLETION_NODE, END)
    return _compile_graph(
        builder,
        checkpointer=saver,
        interrupt_before=[],
        name="promotion-probe",
    )


async def _finish_first_turn(
    saver: AsyncSqliteSaver, receipt: GraphActionReceipt
) -> None:
    """Run the real graph so the checkpoint proves the first turn completed."""
    config: RunnableConfig = {"configurable": {"thread_id": _RUN}}
    await _graph(saver).ainvoke(
        {
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
            "graph_action_receipts": {
                receipt.dispatch_id: receipt.model_dump(mode="json")
            },
        },
        config,
    )


async def _queue_continuation(
    sessions: async_sessionmaker[AsyncSession],
    workspace: Path,
    *,
    key: str = "second-turn",
    content: str = "second turn",
) -> str:
    """Admit one continuation through the production queue repository."""
    async with sessions() as db:
        outcome = await reserve_queued_continuation(
            db,
            QueuedContinuationRequest(
                thread_id=_RUN,
                idempotency_key=key,
                payload=_envelope(content, workspace),
                dispatch_id=f"dispatch-{key}",
                lifetime_deadline_at=datetime.now(UTC) + timedelta(hours=6),
                limits=_ROOMY,
            ),
        )
        await db.commit()
    assert outcome.disposition is QueuedContinuationDisposition.QUEUED
    return outcome.dispatch_id


async def _checkpoint_count(saver: AsyncSqliteSaver) -> int:
    config: RunnableConfig = {"configurable": {"thread_id": _RUN}}
    return len([tuple_ async for tuple_ in saver.alist(config)])


@pytest.mark.asyncio
async def test_a_proven_turn_promotes_instead_of_settling(
    busy_run: PromotionFixture,
) -> None:
    """The next turn takes the run's write authority; the run stays RUNNING."""
    sessions, saver, receipt, workspace = busy_run
    continuation = await _queue_continuation(sessions, workspace)
    await _finish_first_turn(saver, receipt)

    async with sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            saver,
            RecoveryRequest(
                thread_id=_RUN,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=5,
            ),
        )

    assert observed.status is ThreadStatus.RUNNING
    assert observed.condition == CONTINUATION_PROMOTED
    assert observed.changed

    async with sessions() as reader:
        thread = await get_thread(reader, _RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value
        assert thread.is_active
        # The continuation now holds the run's write authority, under a
        # generation of its own so the first turn's receipt cannot speak again.
        assert thread.writer_action_type == (
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
        )
        assert thread.writer_action_receipt_id == continuation
        assert thread.writer_generation == 2
        assert thread.run_revision == 1

        promoted = await _action(reader, continuation)
        assert promoted.applied_at is None
        assert promoted.result_status == (
            ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
        )
        assert promoted.graph_receipt_json is not None
        # The promotion is not the dispatcher, so it gives the lease back for
        # the durable owner that will deliver this turn.
        assert promoted.claim_token is None
        assert promoted.claim_expires_at is None
        # Where it came from survives promotion.
        assert promoted.queue_position == 1
        assert await count_queued_continuations(reader, thread_id=_RUN) == 0


@pytest.mark.asyncio
async def test_the_turn_that_ended_is_recorded_applied_and_its_budget_renewed(
    busy_run: PromotionFixture,
) -> None:
    """The proven turn settles as applied; the next one gets its own deadline."""
    sessions, saver, receipt, workspace = busy_run
    continuation = await _queue_continuation(sessions, workspace)
    await _finish_first_turn(saver, receipt)
    before = datetime.now(UTC)

    async with sessions() as db:
        await reconcile_run_checkpoint(
            db,
            saver,
            RecoveryRequest(
                thread_id=_RUN,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=5,
            ),
        )

    async with sessions() as reader:
        first = await _action(reader, _FIRST_RECEIPT)
        assert first.applied_at is not None
        assert first.result_status == ControlActionResultStatus.APPLIED.value

        promoted = await _action(reader, continuation)
        assert promoted.recovery_deadline_at is not None
        budget = _definition(workspace).run_timeout_seconds
        # Re-derived at promotion from the promoted turn's OWN envelope, not
        # inherited from the reservation's run-lifetime bound.
        assert promoted.recovery_deadline_at >= before + timedelta(seconds=budget - 5)
        assert promoted.recovery_deadline_at <= datetime.now(UTC) + timedelta(
            seconds=budget
        )


@pytest.mark.asyncio
async def test_an_empty_queue_settles_the_run_exactly_as_before(
    busy_run: PromotionFixture,
) -> None:
    """Nothing waiting, nothing changed: the run completes as it always has."""
    sessions, saver, receipt, _workspace = busy_run
    await _finish_first_turn(saver, receipt)

    async with sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            saver,
            RecoveryRequest(
                thread_id=_RUN,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=5,
            ),
        )

    assert observed.status is ThreadStatus.COMPLETED
    assert observed.changed
    async with sessions() as reader:
        thread = await get_thread(reader, _RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_a_promoted_run_keeps_its_history_and_its_admission_slot(
    busy_run: PromotionFixture,
) -> None:
    """Relaying the turn's terminal frame settles nothing on a promoted run.

    The three effects a settlement has are each observable, and each must be
    absent: the run must not reach a terminal status, its superseded
    checkpoints must survive the prune a settled run triggers, and the drain
    gate must still hold the run, because the run has not finished.
    """
    sessions, saver, receipt, workspace = busy_run
    await _queue_continuation(sessions, workspace)
    await _finish_first_turn(saver, receipt)
    history_before = await _checkpoint_count(saver)
    assert history_before > 1, "the probe graph must leave superseded checkpoints"

    gate = DrainGate()
    admitted = await gate.admit(_RUN)
    assert admitted.admitted
    prunes = CheckpointPruneRegistry()

    await relay_event(
        _RUN,
        {"type": "thread_terminal", "status": ThreadStatus.COMPLETED.value},
        session_factory=sessions,
        checkpointer=saver,
        drain_gate=gate,
        prune_registry=prunes,
    )
    await prunes.settle()

    assert gate.is_active(_RUN), "a run with a further turn still holds its slot"
    assert await _checkpoint_count(saver) == history_before
    async with sessions() as reader:
        thread = await get_thread(reader, _RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value


@pytest.mark.asyncio
async def test_relaying_a_terminal_with_no_continuation_still_settles(
    busy_run: PromotionFixture,
) -> None:
    """The same relay path settles and releases when nothing is waiting."""
    sessions, saver, receipt, _workspace = busy_run
    await _finish_first_turn(saver, receipt)

    gate = DrainGate()
    await gate.admit(_RUN)
    prunes = CheckpointPruneRegistry()

    await relay_event(
        _RUN,
        {"type": "thread_terminal", "status": ThreadStatus.COMPLETED.value},
        session_factory=sessions,
        checkpointer=saver,
        drain_gate=gate,
        prune_registry=prunes,
    )
    await prunes.settle()

    assert not gate.is_active(_RUN)
    async with sessions() as reader:
        thread = await get_thread(reader, _RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.COMPLETED.value


async def _action(session: AsyncSession, dispatch_id: str) -> ControlActionModel:
    from ...database import get_control_action_by_dispatch_id

    action = await get_control_action_by_dispatch_id(
        session, thread_id=_RUN, dispatch_id=dispatch_id
    )
    assert action is not None
    return action
