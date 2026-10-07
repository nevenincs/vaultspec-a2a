"""The startup re-dispatch sweep delivers through the lease, like every verb.

The sweep is one dispatcher among several - the direct recovery pass, a client's
own retry, another gateway. The control-action lease is how they agree on who is
delivering a run's accepted work, and the sweep used to deliver outside it: it
could hand the worker a dispatch a live dispatcher was already holding, which the
worker then refuses as a duplicate of work it is doing, or admits as a second
turn on the same run.

Real database through the production session factory, a real accepted action with
its real graph receipt, a real competing claim taken through the production lease
helper, and a real ASGI worker that records what actually arrived.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ...control.action_lease import (
    ControlActionClaimRequest,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
)
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch import redispatch_reconciling_threads
from ...database import (
    begin_write_transaction,
    close_db,
    get_control_action_by_dispatch_id,
    get_session_factory,
    get_thread,
    init_db,
    thread_write_expectation,
)
from ...testing import adopted_spawner, seed_accepted_thread
from ...thread.enums import ControlActionType, ThreadStatus
from ...utils.coercion import decode_json_object
from .conftest import _InProcessWorker

if TYPE_CHECKING:
    from pathlib import Path


async def _seed_reconciling_run(workspace: Path) -> str:
    """Seat one RECONCILING run with the accepted action the sweep redelivers."""
    async with get_session_factory()() as db:
        thread_id, _receipt = await seed_accepted_thread(
            db, status=ThreadStatus.RECONCILING, workspace=workspace
        )
        await db.commit()
    return thread_id


async def _hold_the_accepted_lease(thread_id: str) -> str:
    """Take and commit the accepted action's lease as another dispatcher would.

    Through the production claim helper, so what the sweep meets is a real live
    lease rather than a hand-written column value. Returns the claim token held.
    """
    async with get_session_factory()() as db:
        thread = await get_thread(db, thread_id)
        assert thread is not None
        expectation = thread_write_expectation(thread)
        action = await get_control_action_by_dispatch_id(
            db,
            thread_id=thread_id,
            dispatch_id=expectation.authority.action_receipt_id,
        )
        assert action is not None
        assert action.payload_json is not None and action.dispatch_id is not None
        payload = decode_json_object(action.payload_json)
        assert payload is not None
        request = ControlActionClaimRequest(
            thread_id=thread_id,
            action_type=ControlActionType(action.action_type),
            idempotency_key=action.idempotency_key,
            request_id=action.request_id,
            payload=payload,
            dispatch_id=action.dispatch_id,
            recovery_deadline_at=action.recovery_deadline_at,
            write_expectation=expectation,
        )
        # The reads above opened this session's transaction, and every field the
        # claim needs is already copied out of the rows it loaded: the claim takes
        # the write lock from its own first statement, as production does, and a
        # rollback expires every loaded row.
        await db.rollback()
        await begin_write_transaction(db)
        claim = await prepare_control_action_claim(db, request=request)
        assert claim.acquired, "the first claim on a free lease must be granted"
        assert claim.claim_token is not None
        await finalize_control_action_acceptance(db, claim)
        return claim.claim_token


async def _stored_lease(thread_id: str) -> tuple[str | None, object]:
    """The accepted action's current claim token and application state."""
    async with get_session_factory()() as db:
        thread = await get_thread(db, thread_id)
        assert thread is not None
        action = await get_control_action_by_dispatch_id(
            db,
            thread_id=thread_id,
            dispatch_id=thread_write_expectation(thread).authority.action_receipt_id,
        )
        assert action is not None
        return action.claim_token, action.applied_at


async def _sweep(worker: _InProcessWorker) -> list[float]:
    """Run the production sweep against *worker*, naming its worker contacts."""
    contacts: list[float] = []
    await redispatch_reconciling_threads(
        worker.client,
        WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=30.0),
        adopted_spawner("http://test-worker:8001"),
        record_worker_contact=contacts.append,
    )
    return contacts


@pytest.mark.asyncio
async def test_a_held_lease_blocks_the_startup_redispatch(tmp_path: Path) -> None:
    """A live claim holder keeps the sweep off its run entirely."""
    await close_db()
    await init_db(str(tmp_path / "redispatch-lease-held.db"))
    try:
        thread_id = await _seed_reconciling_run(tmp_path)
        held_token = await _hold_the_accepted_lease(thread_id)
        worker = _InProcessWorker(None)

        contacts = await _sweep(worker)

        assert worker.dispatches == [], (
            "the sweep must not deliver work a live dispatcher is holding"
        )
        assert contacts == []
        # The holder's lease is exactly as it left it, and nothing was applied.
        token, applied_at = await _stored_lease(thread_id)
        assert token == held_token
        assert applied_at is None
        # The run is left for its holder, not failed or moved by the sweep.
        async with get_session_factory()() as db:
            untouched = await get_thread(db, thread_id)
        assert untouched is not None
        assert untouched.status == ThreadStatus.RECONCILING.value
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_a_free_lease_is_taken_and_the_run_is_delivered_once(
    tmp_path: Path,
) -> None:
    """With no holder the sweep claims the action and delivers under its identity."""
    await close_db()
    await init_db(str(tmp_path / "redispatch-lease-free.db"))
    try:
        thread_id = await _seed_reconciling_run(tmp_path)
        async with get_session_factory()() as db:
            seeded = await get_thread(db, thread_id)
        assert seeded is not None
        dispatch_id = thread_write_expectation(seeded).authority.action_receipt_id
        worker = _InProcessWorker(None)

        contacts = await _sweep(worker)

        assert len(worker.dispatches) == 1, worker.dispatches
        delivered = cast("dict[str, object]", worker.dispatches[0])
        assert delivered["thread_id"] == thread_id
        # Delivered under the accepted action's own stable identity, carrying the
        # receipt the leased sequence binds from committed evidence.
        assert delivered["dispatch_id"] == dispatch_id
        assert delivered["graph_action_receipt"] is not None
        assert len(contacts) == 1
        # The sweep now owns the lease it delivered under.
        token, applied_at = await _stored_lease(thread_id)
        assert token is not None
        assert applied_at is None
    finally:
        await close_db()
