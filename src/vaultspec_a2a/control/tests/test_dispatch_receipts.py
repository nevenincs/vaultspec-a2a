"""Real durable ownership elections for immutable graph dispatch evidence."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
from ...thread.enums import ControlActionType, ThreadStatus
from ..action_lease import claim_control_action
from ..dispatch_receipts import bind_graph_action_receipt


@pytest_asyncio.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'receipts.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(sessions):
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
        )
        witness = thread_write_expectation(thread)
        await db.commit()
    return witness


@pytest.mark.asyncio
async def test_retry_preserves_original_receipt_after_state_revision(sessions):
    witness = await _seed(sessions)
    async with sessions() as db:
        claim = await claim_control_action(
            db,
            thread_id="run",
            action_type=ControlActionType.RESUME,
            idempotency_key="resume",
            payload={"option_id": "yes"},
            write_expectation=witness,
        )
        assert claim.acquired
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
    )
    async with sessions() as db:
        bound = await bind_graph_action_receipt(db, request)
    receipt = bound.require_graph_action_receipt()
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
async def test_recovery_cannot_promote_old_action_and_stale_witness_loses(sessions):
    witness = await _seed(sessions)
    request = DispatchRequest(
        dispatch_id="resume",
        action="resume",
        thread_id="run",
        option_id="yes",
        recursion_limit=25,
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
        claim = await claim_control_action(
            db,
            thread_id="run",
            action_type=ControlActionType.RESUME,
            idempotency_key="resume",
            payload={"option_id": "yes"},
            write_expectation=witness,
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
