"""Real durable ownership elections for immutable graph dispatch evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import (
    create_control_action,
    create_thread,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_thread,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ...database.models import Base, RunWriteAuthority
from ...database.session import configure_sqlite_transactions
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ..accepted_input import freeze_accepted_input
from ..action_lease import (
    ControlActionClaimRequest,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
)
from ..dispatch_receipts import bind_graph_action_receipt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ...database.thread_repository import ThreadWriteExpectation


@pytest_asyncio.fixture
async def sessions(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'receipts.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(sessions: async_sessionmaker[AsyncSession]) -> ThreadWriteExpectation:
    async with sessions() as db:
        thread = await create_thread(
            db,
            thread_id="run",
            status=ThreadStatus.INPUT_REQUIRED,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, "initial"
            ),
        )
        await create_control_action(
            db,
            thread_id="run",
            action_type=ControlActionType.INGEST,
            idempotency_key="initial",
            dispatch_id="initial",
            payload={"content": "first"},
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        witness = thread_write_expectation(thread)
        await db.commit()
    return witness


@pytest.mark.asyncio
async def test_delivery_cannot_create_missing_acceptance_evidence(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
):
    await _seed(sessions)
    async with sessions() as db:
        bound = await bind_graph_action_receipt(
            db,
            DispatchRequest(
                dispatch_id="initial",
                action="ingest",
                thread_id="run",
                content="first",
                workspace_root=str(tmp_path),
                recursion_limit=25,
                team_preset="mock-success-single",
                graph_definition=freeze_graph_definition(
                    load_team_config("mock-success-single", workspace_root=tmp_path),
                    workspace_root=tmp_path,
                ),
            ),
        )
        assert bound.graph_action_receipt is None
        await db.commit()
    async with sessions() as observer:
        action = await get_control_action_by_dispatch_id(
            observer,
            thread_id="run",
            dispatch_id="initial",
        )
        assert action is not None
        assert action.graph_receipt_json is None


@pytest.mark.asyncio
async def test_retry_preserves_original_receipt_after_state_revision(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
):
    witness = await _seed(sessions)
    async with sessions() as db:
        claim = await prepare_control_action_claim(
            db,
            request=ControlActionClaimRequest(
                thread_id="run",
                action_type=ControlActionType.RESUME,
                idempotency_key="resume",
                payload=freeze_accepted_input(
                    DispatchRequest(
                        action="resume",
                        thread_id="run",
                        option_id="yes",
                        recursion_limit=25,
                        team_preset="mock-success-single",
                        graph_definition=freeze_graph_definition(
                            load_team_config(
                                "mock-success-single", workspace_root=tmp_path
                            ),
                            workspace_root=tmp_path,
                        ),
                    ),
                    intent={"option_id": "yes"},
                ),
                dispatch_id="resume",
                write_expectation=witness,
                recovery_timeout_seconds=60,
            ),
        )
        assert claim.acquired
        await finalize_control_action_acceptance(db, claim)
    async with sessions() as observer:
        durable = await get_control_action_by_dispatch_id(
            observer, thread_id="run", dispatch_id=claim.dispatch_id
        )
        assert durable is not None
        assert durable.graph_receipt_json is not None
        thread = await get_thread(observer, "run")
        assert thread is not None
        assert thread.writer_action_receipt_id == claim.dispatch_id
    request = DispatchRequest(
        dispatch_id=claim.dispatch_id,
        action="resume",
        thread_id="run",
        option_id="yes",
        recursion_limit=25,
        team_preset="mock-success-single",
        graph_definition=freeze_graph_definition(
            load_team_config("mock-success-single", workspace_root=tmp_path),
            workspace_root=tmp_path,
        ),
    )
    async with sessions() as db:
        bound = await bind_graph_action_receipt(db, request)
    receipt = bound.require_graph_action_receipt()
    changed = request.model_copy(update={"recursion_limit": 26})
    async with sessions() as db:
        refused = await bind_graph_action_receipt(db, changed)
    assert refused.graph_action_receipt is None
    assert receipt.run_revision == 1
    assert receipt.writer_generation == 2
    async with sessions() as db:
        thread = await get_thread(db, "run")
        assert thread is not None
        expectation = thread_write_expectation(thread)
        await elect_thread_status(
            db,
            "run",
            expectation=expectation,
            status=ThreadStatus.RUNNING,
            successor=successor_thread_write_authority(
                expectation,
                action_type=ControlActionType.RESUME,
                action_receipt_id=claim.dispatch_id,
            ),
        )
        await db.commit()
    async with sessions() as db:
        retry = await bind_graph_action_receipt(db, request)
    assert retry.require_graph_action_receipt() == receipt


@pytest.mark.asyncio
async def test_recovery_cannot_promote_old_action_and_stale_witness_loses(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
):
    witness = await _seed(sessions)
    request = DispatchRequest(
        dispatch_id="resume",
        action="resume",
        thread_id="run",
        option_id="yes",
        recursion_limit=25,
        team_preset="mock-success-single",
        graph_definition=freeze_graph_definition(
            load_team_config("mock-success-single", workspace_root=tmp_path),
            workspace_root=tmp_path,
        ),
    )
    async with sessions() as db:
        refused = await bind_graph_action_receipt(db, request)
        assert refused.graph_action_receipt is None
        await elect_thread_status(
            db,
            "run",
            expectation=witness,
            status=ThreadStatus.CANCELLED,
            successor=successor_thread_write_authority(
                witness,
                action_type=ControlActionType.INGEST,
                action_receipt_id="initial",
            ),
        )
        await db.commit()
    async with sessions() as db:
        claim = await prepare_control_action_claim(
            db,
            request=ControlActionClaimRequest(
                thread_id="run",
                action_type=ControlActionType.RESUME,
                idempotency_key="resume",
                payload=freeze_accepted_input(
                    DispatchRequest(
                        action="resume",
                        thread_id="run",
                        option_id="yes",
                        recursion_limit=25,
                        team_preset="mock-success-single",
                        graph_definition=freeze_graph_definition(
                            load_team_config(
                                "mock-success-single", workspace_root=tmp_path
                            ),
                            workspace_root=tmp_path,
                        ),
                    ),
                    intent={"option_id": "yes"},
                ),
                dispatch_id="resume",
                write_expectation=witness,
                recovery_timeout_seconds=60,
            ),
        )
        assert not claim.acquired
        assert not claim.authority_matches
        assert (
            await get_control_action_by_dispatch_id(
                db,
                thread_id="run",
                dispatch_id=claim.dispatch_id,
            )
            is None
        )
        thread = await get_thread(db, "run")
        assert thread is not None
        assert thread.status == ThreadStatus.CANCELLED
        assert thread.writer_action_receipt_id == "initial"


@pytest.mark.asyncio
@pytest.mark.parametrize("finalize", [False, True])
async def test_requested_projection_and_receipt_share_acceptance_commit(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path, finalize: bool
):
    witness = await _seed(sessions)
    async with sessions() as db:
        claim = await prepare_control_action_claim(
            db,
            request=ControlActionClaimRequest(
                thread_id="run",
                action_type=ControlActionType.RESUME,
                idempotency_key="resume",
                payload=freeze_accepted_input(
                    DispatchRequest(
                        action="resume",
                        thread_id="run",
                        option_id="yes",
                        recursion_limit=25,
                        team_preset="mock-success-single",
                        graph_definition=freeze_graph_definition(
                            load_team_config(
                                "mock-success-single", workspace_root=tmp_path
                            ),
                            workspace_root=tmp_path,
                        ),
                    ),
                    intent={"option_id": "yes"},
                ),
                dispatch_id="resume",
                write_expectation=witness,
                recovery_timeout_seconds=60,
            ),
        )
        assert claim.acquired
        row = await get_thread(db, "run")
        assert row is not None
        row.approval_response_action_id = claim.action_id
        before_commit = await bind_graph_action_receipt(
            db,
            DispatchRequest(
                dispatch_id=claim.dispatch_id,
                action="resume",
                thread_id="run",
                option_id="yes",
                recursion_limit=25,
                team_preset="mock-success-single",
                graph_definition=freeze_graph_definition(
                    load_team_config("mock-success-single", workspace_root=tmp_path),
                    workspace_root=tmp_path,
                ),
            ),
        )
        assert before_commit.graph_action_receipt is None
        if finalize:
            await finalize_control_action_acceptance(db, claim)
        # Closing without finalization simulates failure before acceptance.
    async with sessions() as observer:
        action = await get_control_action_by_dispatch_id(
            observer,
            thread_id="run",
            dispatch_id=claim.dispatch_id,
        )
        row = await get_thread(observer, "run")
        assert row is not None
        if finalize:
            assert action is not None
            assert action.graph_receipt_json is not None
            assert action.claim_token == claim.claim_token
            assert row.writer_action_receipt_id == claim.dispatch_id
            assert row.approval_response_action_id == claim.action_id
        else:
            assert action is None
            assert row.writer_action_receipt_id == "initial"
            assert row.approval_response_action_id is None
