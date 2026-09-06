"""Startup and served reads share exact durable graph completion authority."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...database import create_control_action, create_thread, get_thread
from ...database.models import Base, RunWriteAuthority
from ...database.reconciliation import reconcile_threads_on_startup
from ...database.session import configure_sqlite_transactions
from ...graph.nodes.action_completion import (
    GRAPH_COMPLETION_NODE,
    record_graph_completion,
)
from ...ipc.schemas import DispatchRequest
from ...thread.checkpoint_evidence import (
    CheckpointEvidenceKind,
    read_checkpoint_evidence,
)
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.state import TeamState
from ..accepted_input import freeze_accepted_input
from ..dispatch_receipts import prepare_graph_action_receipt
from ..recovery_authority import RecoveryTrigger, reconcile_run_checkpoint
from ..run_discovery_service import discover_active_runs

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


@pytest_asyncio.fixture
async def durable_run(tmp_path, request):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        await create_thread(
            db,
            thread_id="run",
            status=getattr(request, "param", ThreadStatus.RECONCILING),
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, "accepted"
            ),
        )
        await create_control_action(
            db,
            thread_id="run",
            action_type=ControlActionType.INGEST,
            idempotency_key="accepted",
            dispatch_id="accepted",
            payload=freeze_accepted_input(
                DispatchRequest(
                    action="ingest",
                    thread_id="run",
                    content="work",
                    workspace_root=str(tmp_path),
                    recursion_limit=25,
                ),
                intent={"content": "work"},
            ),
        )
        receipt = await prepare_graph_action_receipt(
            db, thread_id="run", dispatch_id="accepted"
        )
        assert receipt is not None
        await db.commit()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.db")) as saver:
        yield sessions, saver, receipt
    await engine.dispose()


def _work(state: TeamState) -> dict[str, object]:
    return {}


def _graph(saver, *, pause=False):
    builder = StateGraph(cast("Any", TeamState))
    builder.add_node("work", _work)
    builder.add_node(GRAPH_COMPLETION_NODE, record_graph_completion)
    builder.add_edge(START, "work")
    builder.add_edge("work", GRAPH_COMPLETION_NODE)
    builder.add_edge(GRAPH_COMPLETION_NODE, END)
    return builder.compile(
        checkpointer=saver, interrupt_before=["work"] if pause else []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["direct", "startup", "discovery"])
async def test_each_entry_settles_checkpoint_completion_and_reads_fresh_state(
    durable_run, entry
):
    sessions, saver, receipt = durable_run
    config: RunnableConfig = {"configurable": {"thread_id": "run"}}
    await _graph(saver).ainvoke(
        {
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
            "graph_action_receipts": {
                receipt.dispatch_id: receipt.model_dump(mode="json")
            },
        },
        config,
    )
    async with sessions() as db:
        if entry == "direct":
            observed = await reconcile_run_checkpoint(
                db,
                saver,
                "run",
                trigger=RecoveryTrigger.READ,
                checkpoint_timeout_seconds=5,
            )
            assert observed.changed
            assert observed.status is ThreadStatus.COMPLETED
        elif entry == "startup":
            summary = await reconcile_threads_on_startup(db, saver)
            assert summary["repair_backlog"] == 0
        else:
            page = await discover_active_runs(db, checkpointer=saver)
            assert page.runs == []
    async with sessions() as reader:
        thread = await get_thread(reader, "run")
        assert thread is not None
        assert thread.status == ThreadStatus.COMPLETED
        assert thread.run_revision == 1


@pytest.mark.asyncio
async def test_empty_pending_writes_do_not_prove_completion(durable_run):
    sessions, saver, receipt = durable_run
    config: RunnableConfig = {"configurable": {"thread_id": "run"}}
    await _graph(saver, pause=True).ainvoke(
        {
            "active_graph_action_receipt": receipt.model_dump(mode="json"),
            "graph_action_receipts": {
                receipt.dispatch_id: receipt.model_dump(mode="json")
            },
        },
        config,
    )
    checkpoint = await saver.aget_tuple(config)
    assert checkpoint is not None
    assert not checkpoint.pending_writes
    evidence = await read_checkpoint_evidence(saver, receipt, timeout_seconds=5)
    assert evidence.kind is CheckpointEvidenceKind.PENDING
    async with sessions() as db:
        observed = await reconcile_run_checkpoint(
            db, saver, "run", trigger=RecoveryTrigger.READ, checkpoint_timeout_seconds=5
        )
        assert not observed.changed
        assert observed.status is ThreadStatus.RECONCILING


@pytest.mark.asyncio
@pytest.mark.parametrize("durable_run", [ThreadStatus.RUNNING], indirect=True)
async def test_only_startup_demotes_unfinished_execution(durable_run):
    sessions, saver, _receipt = durable_run
    async with sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            saver,
            "run",
            trigger=RecoveryTrigger.READ,
            checkpoint_timeout_seconds=5,
        )
        assert observed.status is ThreadStatus.RUNNING
        assert not observed.changed
    async with sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            saver,
            "run",
            trigger=RecoveryTrigger.STARTUP,
            checkpoint_timeout_seconds=5,
        )
        assert observed.status is ThreadStatus.RECONCILING
        assert observed.changed
    async with sessions() as db:
        row = await get_thread(db, "run")
        assert row is not None
        assert row.run_revision == 1
        assert row.repair_reason == "checkpoint_absent"
