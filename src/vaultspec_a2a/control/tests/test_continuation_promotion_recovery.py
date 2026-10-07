"""A gateway killed between promotion and dispatch sends the turn once.

Promotion commits the next turn's write authority and nothing else: the
delivery belongs to the durable recovery owner, which is also what survives a
restart. So the window this suite drives is the real one - the promotion is
durable, the dispatch has not happened, and the process starts again.

Two things have to hold across that window. The startup reconciler must not
read it as abandonment: the run is RUNNING with no live worker precisely
because the promotion dispatcher has not sent yet, and moving it into repair
would strand the turn the dispatcher owns. And the delivery must happen
exactly once however many passes run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ...database import RecoveryAttemptModel, get_thread
from ...database.reconciliation import reconcile_threads_on_startup
from ...thread.enums import ControlActionType, RepairStatus, ThreadStatus
from ..circuit_breaker import WorkerCircuitBreaker
from ..direct_control_recovery import redrive_direct_control_actions
from ..recovery_authority import (
    CONTINUATION_PROMOTED,
    RecoveryRequest,
    RecoveryTrigger,
    reconcile_run_checkpoint,
)
from ..worker_management import LazyWorkerSpawner
from ._continuation import (
    RUN,
    BusyRun,
    busy_run_state,
    finish_turn,
    journal_action,
    queue_continuation,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest_asyncio.fixture
async def busy_run(tmp_path: Path) -> AsyncIterator[BusyRun]:
    async with busy_run_state(tmp_path) as state:
        yield state


async def _promote(run: BusyRun) -> None:
    """Commit the promotion the terminal event would, then stop there."""
    async with run.sessions() as db:
        observed = await reconcile_run_checkpoint(
            db,
            run.saver,
            RecoveryRequest(
                thread_id=RUN,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=5,
            ),
        )
    assert observed.condition == CONTINUATION_PROMOTED


async def _restart_recovery(run: BusyRun, passes: int = 1) -> list[dict[str, object]]:
    """Replay a gateway start: reconcile every live run, then redrive delivery.

    The order is the lifespan's own - startup reconciliation runs before the
    recovery owner is started - because that order is what makes the window
    reachable at all.
    """
    received: list[dict[str, object]] = []
    worker = FastAPI()

    @worker.post("/dispatch")
    async def receive(request: Request) -> JSONResponse:
        received.append(await request.json())
        return JSONResponse({"status": "dispatched"})

    async with run.sessions() as db:
        await reconcile_threads_on_startup(db, run.saver)
        await db.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=worker), base_url="http://worker"
    ) as client:
        for _attempt in range(passes):
            await redrive_direct_control_actions(
                run.sessions,
                worker_client=client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30
                ),
                worker_spawner=LazyWorkerSpawner(
                    worker_url="http://worker", worker_port=8001, auto_spawn=False
                ),
                trace_headers=None,
            )
    return received


@pytest.mark.asyncio
async def test_a_restart_delivers_the_promoted_turn_exactly_once(
    busy_run: BusyRun,
) -> None:
    """One dispatch, under the identity promotion gave it, over two passes."""
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)
    await finish_turn(busy_run.saver, busy_run.receipt)
    await _promote(busy_run)

    received = await _restart_recovery(busy_run, passes=2)

    assert len(received) == 1, received
    sent = received[0]
    assert sent["dispatch_id"] == continuation
    assert sent["action"] == "ingest"
    assert sent["thread_id"] == RUN
    # The promoted turn carries its own accepted envelope, recursion budget
    # included, rather than a program reloaded at delivery.
    assert sent["content"] == "second turn"
    assert sent["recursion_limit"] == 37
    assert sent["graph_definition"] is not None


@pytest.mark.asyncio
async def test_the_startup_reconciler_leaves_the_promotion_window_alone(
    busy_run: BusyRun,
) -> None:
    """A promoted turn awaiting delivery is owned, not abandoned.

    Its checkpoint still names the turn before it, which is exactly what an
    abandoned transition looks like from the outside. The difference is that a
    durable owner is obliged to deliver it, and the run's own accepted
    deadline bounds how long that obligation lasts.
    """
    await queue_continuation(busy_run.sessions, busy_run.workspace)
    await finish_turn(busy_run.saver, busy_run.receipt)
    await _promote(busy_run)

    async with busy_run.sessions() as db:
        await reconcile_threads_on_startup(db, busy_run.saver)
        await db.commit()

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value
        assert thread.repair_status != RepairStatus.NEEDS_RECONCILIATION.value
        assert thread.writer_action_type == (
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
        )


@pytest.mark.asyncio
async def test_the_delivered_turn_leaves_a_durable_attempt_awaiting_its_receipt(
    busy_run: BusyRun,
) -> None:
    """Delivery is not application: the owner keeps the turn until it lands."""
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)
    await finish_turn(busy_run.saver, busy_run.receipt)
    await _promote(busy_run)

    assert len(await _restart_recovery(busy_run)) == 1

    async with busy_run.sessions() as reader:
        attempt = await reader.scalar(
            select(RecoveryAttemptModel).where(RecoveryAttemptModel.thread_id == RUN)
        )
        assert attempt is not None
        assert attempt.action_receipt_id == continuation
        assert attempt.settled_at is None
        promoted = await journal_action(reader, continuation)
        assert promoted.applied_at is None
        # The dispatcher that delivered it holds the lease now, which is what
        # stops a second pass sending the same turn again.
        assert promoted.claim_token is not None
