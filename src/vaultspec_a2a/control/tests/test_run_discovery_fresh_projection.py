"""Active discovery serves only a post-recovery durable projection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import (
    ThreadStatusElectionOutcome,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_thread,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ...database.models import Base, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...ipc.schemas import DispatchRequest
from ...thread.enums import ControlActionType, ThreadStatus
from ..accepted_input import freeze_accepted_input
from ..run_discovery_service import discover_active_runs

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

    from ...database.checkpoints import Checkpointer


@pytest.mark.asyncio
async def test_discovery_discards_projection_captured_before_terminal_winner(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A terminal winner during recovery is absent from the served active page."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    configure_sqlite_transactions(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            authority = RunWriteAuthority(0, 1, ControlActionType.INGEST, "accepted")
            await create_thread(
                db,
                thread_id="terminal-during-discovery",
                status=ThreadStatus.RECONCILING,
                write_authority=authority,
            )
            await create_control_action(
                db,
                thread_id="terminal-during-discovery",
                action_type=ControlActionType.INGEST,
                idempotency_key="accepted",
                dispatch_id="accepted",
                payload=freeze_accepted_input(
                    DispatchRequest(
                        action="ingest",
                        thread_id="terminal-during-discovery",
                        content="work",
                        workspace_root=str(tmp_path),
                        recursion_limit=25,
                    ),
                    intent={"content": "work"},
                ),
            )
            await db.commit()

        async def elect_terminal_winner(
            db: AsyncSession,
            _checkpointer: Checkpointer,
            thread_id: str,
            **_kwargs: Any,
        ) -> None:
            current = await get_thread(db, thread_id)
            assert current is not None
            expectation = thread_write_expectation(current)
            election = await elect_thread_status(
                db,
                thread_id,
                expectation=expectation,
                status=ThreadStatus.COMPLETED,
                successor=successor_thread_write_authority(
                    expectation,
                    action_type=expectation.authority.action_type,
                    action_receipt_id=expectation.authority.action_receipt_id,
                ),
            )
            assert election.outcome is ThreadStatusElectionOutcome.WON
            await db.commit()

        monkeypatch.setattr(
            "vaultspec_a2a.control.run_discovery_service.reconcile_run_checkpoint",
            elect_terminal_winner,
        )
        async with sessions() as db:
            result = await discover_active_runs(
                db,
                checkpointer=cast("Any", object()),
            )

        assert result.runs == []
        assert result.truncated is False
    finally:
        await engine.dispose()
