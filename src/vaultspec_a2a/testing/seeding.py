"""The durable run rows a test seats through production's own repositories.

A run's status is elected against the write authority its creation recorded, and
an election refuses a thread whose authority no journaled action backs. A test
that seats a thread row directly, rather than starting a run over the gateway,
therefore has to journal the action its row names as its writer. Every tier used
to write that seed itself - sometimes as a bare journal row, sometimes as the
accepted create action with its frozen input and graph receipt - and imported the
copies from one another's test modules.

:func:`seed_journaled_thread` seats the bare row for a test that only needs the
election to succeed. :func:`seed_accepted_thread` and :func:`seed_create_action`
seat the accepted create action a recovered or settled run carries, and return
the graph receipt it names. :func:`elect_status` and
:func:`record_completed_checkpoint` then move such a run the way the action that
owns it does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ..control.accepted_input import freeze_accepted_input
from ..control.dispatch_receipts import prepare_graph_action_receipt
from ..control.execution_authority import resolve_execution_authority
from ..database import (
    ThreadStatusElectionOutcome,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_thread,
    thread_write_expectation,
)
from ..ipc.schemas import DispatchRequest
from ..team.team_config import load_team_config
from ..tests._checkpoint_seeding import real_checkpoint
from ..tests._write_authority import make_test_write_authority
from ..thread.action_receipts import GraphCompletionReceipt
from ..thread.enums import ThreadStatus
from ..thread.executable_graph import freeze_graph_definition
from ..thread.idempotency import thread_create_action_key
from .catalog_authority import current_execution_metadata
from .gateway_verbs import DEFAULT_TEAM_PRESET

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database.models import ThreadModel
    from ..thread.action_receipts import GraphActionReceipt

__all__ = [
    "elect_status",
    "record_completed_checkpoint",
    "seed_accepted_thread",
    "seed_completed_authority",
    "seed_create_action",
    "seed_journaled_thread",
    "seed_live_thread",
]

_RECOVERY_WINDOW = timedelta(minutes=5)
_CONTENT = "accepted fixture"


def _recovery_deadline(explicit: datetime | None) -> datetime:
    return explicit or datetime.now(UTC) + _RECOVERY_WINDOW


async def seed_journaled_thread(
    session: AsyncSession,
    *,
    status: ThreadStatus | str,
    thread_id: str | None = None,
    title: str | None = None,
    metadata: str | None = None,
    recovery_deadline_at: datetime | None = None,
) -> ThreadModel:
    """Seat a thread and journal the create action its write authority names.

    The journal row carries no accepted input: it is the minimum a status
    election, a deletion or a desktop boot requires of a thread, for a test that
    does not dispatch the run again.
    """
    authority = make_test_write_authority()
    thread = await create_thread(
        session,
        write_authority=authority,
        thread_id=thread_id,
        status=status,
        title=title,
        metadata=metadata,
    )
    await create_control_action(
        session,
        thread_id=thread.id,
        action_type=authority.action_type,
        idempotency_key=thread_create_action_key(thread.id),
        dispatch_id=authority.action_receipt_id,
        recovery_deadline_at=_recovery_deadline(recovery_deadline_at),
    )
    return thread


async def seed_create_action(
    session: AsyncSession,
    thread_id: str,
    *,
    workspace: Path | None = None,
    team_preset: str = DEFAULT_TEAM_PRESET,
    recovery_deadline_at: datetime | None = None,
) -> GraphActionReceipt:
    """Journal the accepted create action an existing thread's writer names.

    The action carries the frozen graph definition and the execution authority
    of the thread's own metadata, or of *workspace* (the working directory
    unless named) when the thread carries none, and its graph receipt is
    prepared as a real accepted dispatch's is.
    """
    thread = await get_thread(session, thread_id)
    assert thread is not None
    workspace = workspace or Path.cwd()
    metadata = thread.thread_metadata or current_execution_metadata(workspace)
    dispatch = DispatchRequest(
        dispatch_id=thread.writer_action_receipt_id,
        action="ingest",
        thread_id=thread_id,
        content=_CONTENT,
        workspace_root=str(workspace),
        recursion_limit=25,
        team_preset=team_preset,
        graph_definition=freeze_graph_definition(
            load_team_config(team_preset, workspace_root=workspace),
            workspace_root=workspace,
        ),
        model_assignment=resolve_execution_authority(metadata).model_assignment,
    )
    await create_control_action(
        session,
        thread_id=thread_id,
        action_type=thread.writer_action_type,
        idempotency_key=thread_create_action_key(thread_id),
        dispatch_id=thread.writer_action_receipt_id,
        recovery_deadline_at=_recovery_deadline(recovery_deadline_at),
        payload=freeze_accepted_input(dispatch, intent={"content": _CONTENT}),
    )
    receipt = await prepare_graph_action_receipt(
        session, thread_id=thread_id, dispatch_id=thread.writer_action_receipt_id
    )
    assert receipt is not None
    return receipt


async def seed_accepted_thread(
    session: AsyncSession,
    *,
    thread_id: str | None = None,
    status: ThreadStatus | str = ThreadStatus.RUNNING,
    title: str | None = None,
    workspace: Path | None = None,
    team_preset: str = DEFAULT_TEAM_PRESET,
    recovery_deadline_at: datetime | None = None,
) -> tuple[str, GraphActionReceipt]:
    """Seat a thread with its accepted create action, and name both.

    The thread carries the current execution authority of *workspace* (the
    working directory unless named). The session is left uncommitted.
    """
    workspace = workspace or Path.cwd()
    thread = await create_thread(
        session,
        write_authority=make_test_write_authority(),
        thread_id=thread_id,
        status=status,
        team_preset=team_preset,
        title=title,
        metadata=current_execution_metadata(workspace),
    )
    receipt = await seed_create_action(
        session,
        thread.id,
        workspace=workspace,
        team_preset=team_preset,
        recovery_deadline_at=recovery_deadline_at,
    )
    return thread.id, receipt


async def seed_live_thread(
    session_factory: async_sessionmaker[AsyncSession], *, title: str
) -> tuple[str, GraphActionReceipt]:
    """Commit a running thread with the accepted action startup recovery requires."""
    async with session_factory() as session:
        seeded = await seed_accepted_thread(session, title=title)
        await session.commit()
        return seeded


async def elect_status(
    session: AsyncSession,
    thread_id: str,
    status: ThreadStatus,
    *,
    failure_reason: str | None = None,
    provider_condition: str | None = None,
) -> None:
    """Move a run to *status* as the action that owns it does, from its own row.

    The witness is the row as it stands and the writer is the action already
    holding the run, so this is the state-only election a settlement makes. It
    fails loudly when the run holds no journal row for its writer, which no
    election accepts.
    """
    thread = await get_thread(session, thread_id)
    assert thread is not None
    expectation = thread_write_expectation(thread)
    authority = expectation.authority
    election = await elect_thread_status(
        session,
        thread_id,
        expectation=expectation,
        status=status,
        action_type=authority.action_type,
        action_receipt_id=authority.action_receipt_id,
        failure_reason=failure_reason,
        provider_condition=provider_condition,
    )
    assert election.outcome is ThreadStatusElectionOutcome.WON


async def record_completed_checkpoint(
    checkpointer: AsyncSqliteSaver, receipt: GraphActionReceipt
) -> None:
    """Write the checkpoint a run leaves once the action *receipt* names completed."""
    config: RunnableConfig = {
        "configurable": {"thread_id": receipt.thread_id, "checkpoint_ns": ""}
    }
    checkpoint = await real_checkpoint()
    checkpoint["id"] = f"cp-{receipt.thread_id}"
    checkpoint["channel_values"] = {
        "active_graph_action_receipt": receipt.model_dump(mode="json"),
        "graph_action_receipts": {receipt.dispatch_id: receipt.model_dump(mode="json")},
        "graph_completion_receipts": {
            receipt.dispatch_id: GraphCompletionReceipt(
                schema_version="graph-completion-v1",
                action=receipt,
                outcome="completed",
            ).model_dump(mode="json")
        },
    }
    checkpoint["channel_versions"] = {
        "active_graph_action_receipt": checkpointer.get_next_version(None, None),
        "graph_action_receipts": checkpointer.get_next_version(None, None),
        "graph_completion_receipts": checkpointer.get_next_version(None, None),
    }
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        checkpoint["channel_versions"],
    )


async def seed_completed_authority(
    session: AsyncSession, checkpointer: AsyncSqliteSaver, *, title: str
) -> tuple[str, GraphActionReceipt]:
    """Commit a running thread whose checkpoint shows its create action completed."""
    thread_id, receipt = await seed_accepted_thread(session, title=title)
    await session.commit()
    await record_completed_checkpoint(checkpointer, receipt)
    return thread_id, receipt
