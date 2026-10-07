"""A failed or cancelled turn refuses the continuation waiting behind it.

Promotion waits on a proven terminal checkpoint, and only a completed turn
produces one. A turn that settles FAILED or CANCELLED settles from failure or
cessation evidence instead, so it is not the boundary a continuation queued
behind: there is no state for a next turn to continue from, and a cancelled
run is leaving. Such a run settles with its own terminal, and what was waiting
on it has to be answered in the same breath.

Left alone, a queued row on a settled run waits for an event that can never
arrive - promoted by nothing, reported to no one. That is the silent drop the
queue rules forbid, which is why the refusal is asserted here as part of the
settlement rather than as a later sweep: when the settlement does not happen,
nothing is refused either.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from ...database import (
    ThreadStatusElectionOutcome,
    begin_write_transaction,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_thread,
    thread_write_expectation,
)
from ...database.session import close_db, get_session_factory, init_db
from ...ipc.schemas import DispatchRequest
from ...thread import RunWriteAuthority
from ...thread.enums import ControlActionResultStatus, ControlActionType, ThreadStatus
from ...thread.failure_evidence import (
    GraphFailureEvidence,
    failure_detail_fingerprint,
)
from ...thread.idempotency import thread_create_action_key
from ..accepted_input import freeze_accepted_input
from ..circuit_breaker import WorkerCircuitBreaker
from ..dispatch import redispatch_reconciling_threads
from ..dispatch_receipts import prepare_graph_action_receipt
from ..event_handlers import _handle_terminal_event
from ..repositories import count_queued_continuations
from ..worker_management import LazyWorkerSpawner
from ._catalog_authority import current_execution_metadata
from ._continuation import (
    FIRST_RECEIPT,
    PRESET,
    RUN,
    BusyRun,
    envelope,
    journal_action,
    queue_continuation,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_FAILURE_DETAIL = "the provider ended the turn before a response"
_FAILURE_CONDITION = "network_unreachable"
_CANCEL_RECEIPT = "cancel-dispatch"


def _failure_payload(
    run: BusyRun, *, detail: str = _FAILURE_DETAIL
) -> dict[str, object]:
    """Build the terminal event a worker sends when this run's turn failed."""
    evidence = GraphFailureEvidence(
        schema_version="graph-failure-v1",
        action=run.receipt,
        outcome="failed",
        detail_fingerprint=failure_detail_fingerprint(detail),
        provider_condition=_FAILURE_CONDITION,
    )
    return {
        "event_type": "thread_terminal",
        "status": "failed",
        "error_detail": detail,
        "provider_condition": _FAILURE_CONDITION,
        "failure_evidence": evidence.model_dump(mode="json"),
    }


def _cancellation_payload() -> dict[str, object]:
    """Build the terminal event a worker sends when it observed cessation."""
    return {
        "event_type": "thread_terminal",
        "status": "cancelled",
        "cancellation_evidence": {
            "schema_version": "cancellation-evidence-v1",
            "dispatch_id": _CANCEL_RECEIPT,
            "outcome": "ceased",
        },
    }


async def _take_cancel_authority(run: BusyRun) -> None:
    """Move the busy run to CANCELLING under a real accepted cancel action.

    The same two durable writes the cancel verb makes: the accepted journal
    action, then the election that hands the run's write authority to its
    receipt. A continuation queued before this keeps its place, which is the
    shape the refusal has to answer.
    """
    async with run.sessions() as db:
        await begin_write_transaction(db)
        thread = await get_thread(db, RUN)
        assert thread is not None
        await create_control_action(
            db,
            thread_id=RUN,
            action_type=ControlActionType.CANCEL,
            idempotency_key=f"cancel:{RUN}",
            dispatch_id=_CANCEL_RECEIPT,
            payload=freeze_accepted_input(
                DispatchRequest(
                    dispatch_id=_CANCEL_RECEIPT,
                    action="cancel",
                    thread_id=RUN,
                    recursion_limit=25,
                ),
                intent={"cancel": True},
            ),
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        expectation = thread_write_expectation(thread)
        election = await elect_thread_status(
            db,
            RUN,
            expectation=expectation,
            status=ThreadStatus.CANCELLING,
            action_type=ControlActionType.CANCEL,
            action_receipt_id=_CANCEL_RECEIPT,
        )
        assert election.outcome is ThreadStatusElectionOutcome.WON
        await db.commit()


async def _assert_refused_in_place(
    sessions: async_sessionmaker[AsyncSession], dispatch_id: str
) -> None:
    """The waiting row is settled as an invalid-state refusal, place retained."""
    async with sessions() as reader:
        refused = await journal_action(reader, dispatch_id)
        assert refused.result_status == (
            ControlActionResultStatus.REJECTED_INVALID_STATE.value
        )
        assert refused.applied_at is not None
        assert refused.claim_token is None
        assert refused.claim_expires_at is None
        # The record still says what was refused and where it sat.
        assert refused.queue_position == 1
        # Nothing is left waiting on a run that can never promote it.
        assert await count_queued_continuations(reader, thread_id=RUN) == 0


@pytest.mark.asyncio
async def test_a_failed_turn_refuses_the_continuation_waiting_on_it(
    busy_run: BusyRun,
) -> None:
    """A run settling FAILED answers its queue instead of stranding it."""
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)

    await _handle_terminal_event(
        RUN, _failure_payload(busy_run), session_factory=busy_run.sessions
    )

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.FAILED.value
    await _assert_refused_in_place(busy_run.sessions, continuation)


@pytest.mark.asyncio
async def test_a_cancelled_run_refuses_the_continuation_waiting_on_it(
    busy_run: BusyRun,
) -> None:
    """A run settling CANCELLED answers its queue instead of stranding it."""
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)
    await _take_cancel_authority(busy_run)

    await _handle_terminal_event(
        RUN, _cancellation_payload(), session_factory=busy_run.sessions
    )

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.CANCELLED.value
    await _assert_refused_in_place(busy_run.sessions, continuation)


@pytest.mark.asyncio
async def test_a_settlement_that_is_refused_refuses_nothing_in_the_queue(
    busy_run: BusyRun,
) -> None:
    """No settlement, no refusal: the two are one transaction or neither.

    The evidence here is honest about its own action but describes a different
    failure, which is exactly the case the terminal election rejects. The run
    keeps running, so the continuation keeps its place and its lease; a
    refusal written anyway would have discarded accepted work for an event
    that changed nothing.
    """
    continuation = await queue_continuation(busy_run.sessions, busy_run.workspace)
    published: list[str] = []

    payload = _failure_payload(busy_run)
    payload["error_detail"] = "a different failure"

    await _handle_terminal_event(
        RUN,
        payload,
        session_factory=busy_run.sessions,
        publish_terminal=lambda: published.append("terminal"),
    )
    assert published == [], "a refused terminal must not close the live stream"

    async with busy_run.sessions() as reader:
        thread = await get_thread(reader, RUN)
        assert thread is not None
        assert thread.status == ThreadStatus.RUNNING.value
        waiting = await journal_action(reader, continuation)
        assert waiting.result_status == ControlActionResultStatus.QUEUED.value
        assert waiting.applied_at is None
        assert waiting.claim_token is not None
        assert await count_queued_continuations(reader, thread_id=RUN) == 1

    await _handle_terminal_event(
        RUN,
        _failure_payload(busy_run),
        session_factory=busy_run.sessions,
        publish_terminal=lambda: published.append("terminal"),
    )
    assert published == ["terminal"]
    await _assert_refused_in_place(busy_run.sessions, continuation)


def _authority_absent(workspace: Path) -> str:
    """Stored metadata naming a project but no execution authority at all."""
    return json.dumps({"workspace_root": str(workspace.resolve())})


def _project_absent(workspace: Path) -> str:
    """Stored metadata carrying current authority but naming no project."""
    stored: dict[str, object] = json.loads(current_execution_metadata(workspace))
    del stored["workspace_root"]
    return json.dumps(stored)


async def _seed_reconciling_run(
    sessions: async_sessionmaker[AsyncSession], workspace: Path, metadata: str
) -> None:
    """Seed one RECONCILING run with a real accepted turn and its receipt."""
    async with sessions() as db:
        await create_thread(
            db,
            thread_id=RUN,
            status=ThreadStatus.RECONCILING,
            team_preset=PRESET,
            metadata=metadata,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, FIRST_RECEIPT
            ),
        )
        await create_control_action(
            db,
            thread_id=RUN,
            action_type=ControlActionType.INGEST,
            idempotency_key=thread_create_action_key(RUN),
            dispatch_id=FIRST_RECEIPT,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=30),
            payload=envelope("first turn", workspace),
        )
        assert (
            await prepare_graph_action_receipt(
                db, thread_id=RUN, dispatch_id=FIRST_RECEIPT
            )
            is not None
        )
        await db.commit()


@pytest.mark.parametrize("stored_metadata", [_authority_absent, _project_absent])
@pytest.mark.asyncio
async def test_the_recovery_sweep_refuses_the_queue_of_a_run_it_fails(
    tmp_path: Path, stored_metadata: Callable[[Path], str]
) -> None:
    """The sweep's own per-run refusals are settlements, and answer the queue.

    A run whose continuation outlived its promotion lease is reconciled like
    any other, and the sweep fails it when its stored authority or its project
    is gone. Those two refusals end the run as surely as a worker's failure
    terminal does, so the turn waiting behind them cannot be left queued.
    """
    await close_db()
    await init_db(str(tmp_path / "sweep.db"))
    try:
        sessions = get_session_factory()
        await _seed_reconciling_run(sessions, tmp_path, stored_metadata(tmp_path))
        continuation = await queue_continuation(sessions, tmp_path)

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.adopt_worker()
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            await redispatch_reconciling_threads(
                client,
                WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=999.0),
                spawner,
                record_worker_contact=lambda _when: pytest.fail(
                    "an unrecoverable run reached worker dispatch"
                ),
            )

        async with sessions() as reader:
            thread = await get_thread(reader, RUN)
            assert thread is not None
            assert thread.status == ThreadStatus.FAILED.value
        await _assert_refused_in_place(sessions, continuation)
    finally:
        await close_db()
