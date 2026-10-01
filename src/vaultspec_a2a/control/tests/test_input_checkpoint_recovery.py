"""Gateway recovery reads a crashed run's staged input as that run's own.

A worker killed between the checkpoint LangGraph commits for a run's input and
the first superstep that consumes it leaves a checkpoint whose committed
channels carry no action receipt. Gateway recovery reads the same evidence the
worker's preflight does, so it must name that checkpoint this action's, still
pending, rather than report the run's own input as a foreign checkpoint and
record that as the reason the run needs repair.

A real SQLite application database and a real SQLite checkpoint store, with
the checkpoint written by a real graph run and replayed into the store through
the saver's own API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import create_control_action, create_thread, get_thread
from ...database.models import Base, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...tests._checkpoint_seeding import real_input_checkpoint
from ...thread.checkpoint_evidence import CheckpointEvidenceKind
from ...thread.enums import ControlActionType, RepairStatus, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ..accepted_input import freeze_accepted_input
from ..dispatch_receipts import prepare_graph_action_receipt
from ..recovery_authority import (
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from ...thread.action_receipts import GraphActionReceipt

_THREAD = "crashed-at-input"
_DISPATCH = "accepted"

CrashedRun = tuple[
    async_sessionmaker[AsyncSession], AsyncSqliteSaver, "GraphActionReceipt"
]


@pytest_asyncio.fixture
async def crashed_at_input(tmp_path: Path) -> AsyncIterator[CrashedRun]:
    """A run the gateway still believes is running, with only its input durable."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        await create_thread(
            db,
            thread_id=_THREAD,
            status=ThreadStatus.RUNNING,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, _DISPATCH
            ),
        )
        await create_control_action(
            db,
            thread_id=_THREAD,
            action_type=ControlActionType.INGEST,
            idempotency_key=f"thread-create:{_THREAD}",
            dispatch_id=_DISPATCH,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            payload=freeze_accepted_input(
                DispatchRequest(
                    action="ingest",
                    thread_id=_THREAD,
                    content="work",
                    workspace_root=str(tmp_path),
                    recursion_limit=25,
                    team_preset="mock-success-single",
                    graph_definition=freeze_graph_definition(
                        load_team_config(
                            "mock-success-single", workspace_root=tmp_path
                        ),
                        workspace_root=tmp_path,
                    ),
                ),
                intent={"content": "work"},
            ),
        )
        receipt = await prepare_graph_action_receipt(
            db, thread_id=_THREAD, dispatch_id=_DISPATCH
        )
        assert receipt is not None
        await db.commit()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.db")) as saver:
        checkpoint, metadata = await real_input_checkpoint(
            {
                "thread_id": _THREAD,
                "active_graph_action_receipt": receipt.model_dump(mode="json"),
                "graph_action_receipts": {
                    receipt.dispatch_id: receipt.model_dump(mode="json")
                },
            }
        )
        config: RunnableConfig = {
            "configurable": {"thread_id": _THREAD, "checkpoint_ns": ""}
        }
        await saver.aput(config, checkpoint, metadata, checkpoint["channel_versions"])
        yield sessions, saver, receipt
    await engine.dispose()


@pytest.mark.asyncio
async def test_startup_recovery_names_the_staged_input_as_this_run_pending(
    crashed_at_input: CrashedRun,
) -> None:
    """The run is sent for repair as pending, not as a checkpoint of another action."""
    sessions, saver, _receipt = crashed_at_input
    async with sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            saver,
            RecoveryRequest(
                thread_id=_THREAD,
                trigger=RecoveryTrigger.STARTUP,
                checkpoint_timeout_seconds=5,
            ),
        )

    assert observed.condition == CheckpointEvidenceKind.PENDING.value
    # Still unfinished work, so recovery holds it for redelivery and settles
    # nothing off a checkpoint no superstep has written to.
    assert observed.status is ThreadStatus.RECONCILING
    assert observed.changed

    async with sessions() as reader:
        thread = await get_thread(reader, _THREAD)
        assert thread is not None
        assert thread.status == ThreadStatus.RECONCILING
        assert thread.repair_reason == CheckpointEvidenceKind.PENDING.value
        assert thread.repair_status == RepairStatus.NEEDS_RECONCILIATION


@pytest.mark.asyncio
async def test_a_read_leaves_the_crashed_run_running_for_its_redelivery(
    crashed_at_input: CrashedRun,
) -> None:
    """A served read must not move a run whose input alone is durable."""
    sessions, saver, _receipt = crashed_at_input
    async with sessions() as db:
        observed: Any = await reconcile_run_checkpoint(
            db,
            saver,
            RecoveryRequest(
                thread_id=_THREAD,
                trigger=RecoveryTrigger.READ,
                checkpoint_timeout_seconds=5,
            ),
        )

    assert observed.condition == CheckpointEvidenceKind.PENDING.value
    assert observed.status is ThreadStatus.RUNNING
    assert not observed.changed
