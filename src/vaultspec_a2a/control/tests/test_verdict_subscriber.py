"""Integration tests for the verdict subscriber's correlation and cursor paths.

Real aiosqlite database and a real LangGraph ``AsyncSqliteSaver`` checkpointer,
no mocks. These cover the two internals that do not require the engine or the
worker: correlating an inbound verdict's ids to a parked run through its
checkpointed ``TeamState`` references, and the durable cursor that survives a
gateway restart. The engine-facing SSE consumption is proved live in
``test_verdict_subscriber_live``.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import anyio
import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from fastapi import FastAPI

from ...api.tests.clarification_harness import new_state_graph
from ...authoring import AuthoringClient, LifecycleEvent, StreamError
from ...control.action_lease import CONTROL_ACTION_LEASE_TTL, claim_control_action
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.event_handlers import relay_event
from ...control.verdict_subscriber import (
    VerdictSubscriber,
    _gate_resume_verdict,
    _iter_recovery_proposals,
    _proposal_reconcile_verdict,
    _recovery_high_water,
    _StreamInterruptedError,
    _verdict_resume_idempotency_key,
    _verdict_resume_payload,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
    get_authoring_cursor,
    get_control_action_by_idempotency_key,
    get_permission_request,
    get_thread,
    record_permission_request,
    update_thread_status,
)
from ...database.models import Base
from ...thread.enums import ControlActionType, PermissionRequestStatus, ThreadStatus
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge


@pytest_asyncio.fixture
async def session_factory(
    tmp_path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A real file-backed aiosqlite session factory with the schema created."""
    db_file = tmp_path / "subscriber.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _make_subscriber(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    worker_client: httpx.AsyncClient,
) -> VerdictSubscriber:
    """Construct a subscriber with real (unused-in-correlation) dispatch deps."""
    return VerdictSubscriber(
        session_factory=session_factory,
        checkpointer=checkpointer,
        worker_client=worker_client,
        circuit_breaker=WorkerCircuitBreaker(
            failure_threshold=3, recovery_timeout=30.0
        ),
        worker_spawner=LazyWorkerSpawner(
            worker_url="http://127.0.0.1:1", worker_port=1, auto_spawn=False
        ),
        endpoint_provider=lambda: None,
        recursion_limit=25,
    )


def _install_receipt_graph(
    executor: Executor,
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> None:
    """Register a real graph so a resume crosses Executor application."""

    async def complete(_state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="resumed")], "next": "FINISH"}

    builder = new_state_graph()
    builder.add_node("worker", complete)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    executor.register_compiled_graph(
        thread_id,
        ("verdict-receipt-preset", None, False),
        builder.compile(checkpointer=checkpointer),
    )


@asynccontextmanager
async def _worker_runtime(
    checkpointer: AsyncSqliteSaver,
    *,
    receipt_threads: tuple[str, ...] = (),
) -> AsyncGenerator[tuple[httpx.AsyncClient, FastAPI, WorkerBridge]]:
    bridge = WorkerBridge("http://127.0.0.1:1", "verdict-receipt-test")
    executor = Executor(checkpointer, bridge)
    for thread_id in receipt_threads:
        _install_receipt_graph(executor, checkpointer, thread_id)
    app = create_worker_app()
    app.state.executor = executor
    async with anyio.create_task_group() as tasks:
        app.state.task_group = tasks
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://worker",
        ) as client:
            yield client, app, bridge
        tasks.cancel_scope.cancel()
    await executor.shutdown()
    await bridge.close()


async def _wait_for_receipt(
    bridge: WorkerBridge,
    dispatch_id: str,
) -> dict[str, object]:
    with anyio.fail_after(5.0):
        while True:
            buffered = cast(
                "list[dict[str, object]]",
                getattr(bridge, "_event_buffer", []),
            )
            for item in buffered:
                candidate = item.get("payload")
                candidate_mapping = (
                    cast("dict[str, object]", candidate)
                    if isinstance(candidate, dict)
                    else None
                )
                if (
                    candidate_mapping is not None
                    and candidate_mapping.get("type") == "dispatch_applied"
                    and candidate_mapping.get("dispatch_id") == dispatch_id
                ):
                    return candidate_mapping
            await anyio.sleep(0.01)
    raise AssertionError("dispatch application receipt was not emitted")


async def _seed_parked_thread(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    proposal_ids: list[str],
    changeset_ids: list[str],
    gate_pending: str | None = None,
    team_preset: str | None = None,
) -> None:
    """Create an INPUT_REQUIRED thread with a checkpoint carrying authoring ids."""
    await checkpointer.setup()
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    checkpoint["channel_values"]["authoring_proposal_ids"] = proposal_ids
    checkpoint["channel_values"]["authoring_changeset_ids"] = changeset_ids
    if gate_pending is not None:
        checkpoint["channel_values"]["gate_pending_proposal_id"] = gate_pending
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await create_thread(
            session,
            thread_id=thread_id,
            team_preset=team_preset,
        )
        await update_thread_status(session, thread_id, ThreadStatus.INPUT_REQUIRED)
        await session.commit()


@pytest.mark.asyncio
async def test_resume_resolves_the_answered_document_gate_permission_row(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A subscriber-driven resume resolves the answered gate's durable row.

    The document gate parks with a durable ``document_approval_request`` permission
    row; the verdict subscriber resumes the run past it via ``Command(resume)``,
    bypassing the permission-response FSM. If the row were left pending it would be
    stranded once the checkpoint interrupt it belonged to is gone, and run-status -
    the authoritative recovery read - would assert ``recovery_required`` and mask
    the real ``awaiting_adr_decision`` phase. On a successful resume the row is
    marked applied only after the real Executor emits its exact stable-dispatch
    receipt; a co-resident tool-permission row is left untouched.
    """
    thread_id = "gate-resume"
    checkpoints = tmp_path / "cp-resume.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id=thread_id,
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
            team_preset="verdict-receipt-preset",
        )
        async with session_factory() as session:
            await record_permission_request(
                session,
                request_id=f"{thread_id}:research-gate",
                thread_id=thread_id,
                pause_reason_type="document_approval_request",
                description="Approve the research document",
                allowed_options=[
                    {"option_id": "approve", "name": "Approve", "kind": "allow_once"}
                ],
            )
            await record_permission_request(
                session,
                request_id=f"{thread_id}:tool",
                thread_id=thread_id,
                pause_reason_type="Bash",
                description="Run a command",
                allowed_options=[],
            )
            await session.commit()

        async with _worker_runtime(
            checkpointer,
            receipt_threads=(thread_id,),
        ) as (worker_client, worker_app, bridge):
            subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
            await subscriber._resume_with_verdict(
                thread_id, "approved", None, {"proposal:research"}
            )

            async with session_factory() as session:
                gate_row = await get_permission_request(
                    session, f"{thread_id}:research-gate"
                )
                action = await get_control_action_by_idempotency_key(
                    session,
                    thread_id=thread_id,
                    idempotency_key=_verdict_resume_idempotency_key(
                        "proposal:research"
                    ),
                )
                thread = await get_thread(session, thread_id)
            assert gate_row is not None
            assert gate_row.request_status == PermissionRequestStatus.PENDING.value
            assert action is not None
            assert action.applied_at is None
            assert thread is not None
            assert thread.status == ThreadStatus.INPUT_REQUIRED.value
            assert len(worker_app.state.dispatch_ids) == 1

            receipt = await _wait_for_receipt(bridge, action.dispatch_id)
            await relay_event(
                thread_id,
                receipt,
                session_factory=session_factory,
            )

        async with session_factory() as session:
            gate_row = await get_permission_request(
                session, f"{thread_id}:research-gate"
            )
            tool_row = await get_permission_request(session, f"{thread_id}:tool")
            assert gate_row is not None
            assert gate_row.request_status == PermissionRequestStatus.APPLIED.value
            # A non-document permission is not touched by the gate resolution.
            assert tool_row is not None
            assert tool_row.request_status == PermissionRequestStatus.PENDING.value
            thread = await get_thread(session, thread_id)
            assert thread is not None
            assert thread.status == ThreadStatus.RUNNING.value


@pytest.mark.asyncio
async def test_correlates_parked_thread_by_proposal_id(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-proposal.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-parked-1",
            proposal_ids=["prop_abc"],
            changeset_ids=["cs_abc"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        matched = await subscriber._find_parked_thread({"prop_abc"})
        assert matched == "thread-parked-1"


@pytest.mark.asyncio
async def test_correlates_parked_thread_by_changeset_id(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-changeset.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-parked-2",
            proposal_ids=[],
            changeset_ids=["cs_xyz"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        matched = await subscriber._find_parked_thread({"cs_xyz", "unrelated"})
        assert matched == "thread-parked-2"


@pytest.mark.asyncio
async def test_unknown_ids_correlate_to_nothing(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-none.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-parked-3",
            proposal_ids=["prop_known"],
            changeset_ids=["cs_known"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await subscriber._find_parked_thread({"prop_missing"}) is None


@pytest.mark.asyncio
async def test_non_parked_thread_is_not_correlated(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A RUNNING thread is not a gate-parked candidate even with matching ids."""
    checkpoints = tmp_path / "cp-running.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-running",
            proposal_ids=["prop_running"],
            changeset_ids=[],
        )
        async with session_factory() as session:
            await update_thread_status(session, "thread-running", ThreadStatus.RUNNING)
            await session.commit()
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await subscriber._find_parked_thread({"prop_running"}) is None


@pytest.mark.asyncio
async def test_cursor_advances_and_survives_restart(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The durable cursor a restarted subscriber reads is the last it advanced."""
    checkpoints = tmp_path / "cp-cursor.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        first = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await first._read_cursor() == 0
        await first._advance_cursor(17)

        # A fresh subscriber instance models the post-restart gateway process.
        second = _make_subscriber(session_factory, checkpointer, worker_client)
        assert await second._read_cursor() == 17

    async with session_factory() as session:
        assert await get_authoring_cursor(session) == 17


# ---------------------------------------------------------------------------
# Frame- and snapshot-processing internals over synthetic decoded payloads.
# No engine, no mocks: real DB + checkpointer, and a real (unreachable) worker
# client so the resume-dispatch path exercises genuine failure handling.
# ---------------------------------------------------------------------------


def _recovery_snapshot(items: list[dict[str, object]], *, latest: int) -> dict:
    """Build a recovery-snapshot ``data`` payload in the engine's shape."""
    return {
        "family": "recovery",
        "latest_outbox_seq": latest,
        "snapshot": {"proposals": {"items": items, "truncated": False, "cap": 50}},
    }


def test_iter_recovery_proposals_extracts_status_and_ids() -> None:
    data = _recovery_snapshot(
        [
            {
                "changeset_id": "cs_1",
                "status": "approved",
                "approval": {"proposal_id": "prop_1"},
            },
            {"changeset_id": "cs_2", "status": "draft"},
        ],
        latest=42,
    )
    extracted = _iter_recovery_proposals(data)
    assert extracted == [
        {
            "status": "approved",
            "ids": {"cs_1", "prop_1"},
            "approval": {"proposal_id": "prop_1"},
        },
        {"status": "draft", "ids": {"cs_2"}, "approval": None},
    ]


def test_iter_recovery_proposals_accepts_bare_list_and_skips_malformed() -> None:
    data = {
        "snapshot": {
            "proposals": [
                {"changeset_id": "cs_ok", "status": "rejected"},
                {1: "not-a-json-object"},
                {"status": "approved"},  # no ids -> skipped
                {"changeset_id": "cs_x"},  # no status -> skipped
                "garbage",
            ]
        }
    }
    assert _iter_recovery_proposals(data) == [
        {"status": "rejected", "ids": {"cs_ok"}, "approval": None}
    ]


def test_iter_recovery_proposals_tolerates_missing_structure() -> None:
    assert _iter_recovery_proposals(None) == []
    assert _iter_recovery_proposals({}) == []
    assert _iter_recovery_proposals({"snapshot": {}}) == []


def test_recovery_high_water_reads_int_or_none() -> None:
    assert _recovery_high_water({"latest_outbox_seq": 7}) == 7
    assert _recovery_high_water({"latest_outbox_seq": True}) is None
    assert _recovery_high_water({}) is None
    assert _recovery_high_water(None) is None


@pytest.mark.asyncio
async def test_process_frame_raises_on_stream_error(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-frame-err.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await checkpointer.setup()
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        client = AuthoringClient("http://127.0.0.1:1", "tok")
        frame = StreamError(error_kind="authoring_store_unavailable", error="down")
        with pytest.raises(_StreamInterruptedError):
            await subscriber._process_frame(client, frame)
        await client.aclose()


@pytest.mark.asyncio
async def test_process_frame_advances_cursor_for_non_verdict_event(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A non-verdict lifecycle frame advances the cursor without dispatching."""
    checkpoints = tmp_path / "cp-frame-adv.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await checkpointer.setup()
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        client = AuthoringClient("http://127.0.0.1:1", "tok")
        event = LifecycleEvent(
            seq=9,
            event_kind="approval.requested",
            aggregate_kind="changeset",
            aggregate_id="cs_pending",
            data={},
        )
        await subscriber._process_frame(client, event)
        await client.aclose()

    async with session_factory() as session:
        assert await get_authoring_cursor(session) == 9


@pytest.mark.asyncio
async def test_process_event_non_verdict_is_a_noop(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-ev-noverdict.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-noverdict",
            proposal_ids=["prop_nv"],
            changeset_ids=[],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        event = LifecycleEvent(
            seq=1,
            event_kind="approval.requested",
            aggregate_kind="approval",
            aggregate_id="prop_nv",
            data={},
        )
        await subscriber._process_event(event)

    async with session_factory() as session:
        thread = await get_thread(session, "thread-noverdict")
        assert thread is not None
        # No verdict -> the parked run is left parked.
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_process_event_verdict_with_unreachable_worker_does_not_crash(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A real verdict correlates and dispatches; an unreachable worker is handled.

    The dispatch goes to a real worker client on a dead port, so ``safe_dispatch``
    exercises genuine ``WorkerUnreachableError`` handling (no double). The run
    stays parked because the resume never landed.
    """
    checkpoints = tmp_path / "cp-ev-verdict.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-verdict",
            proposal_ids=["prop_v"],
            changeset_ids=[],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        event = LifecycleEvent(
            seq=2,
            event_kind="approval.resolved",
            aggregate_kind="approval",
            aggregate_id="approval_v",
            data={"decision": "approve", "proposal_id": "prop_v", "comment": "ok"},
        )
        # Must not raise despite the worker being unreachable.
        await subscriber._process_event(event)

    async with session_factory() as session:
        thread = await get_thread(session, "thread-verdict")
        assert thread is not None
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_reconcile_recovery_no_verdict_status_is_a_noop(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    checkpoints = tmp_path / "cp-recon-noop.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-recon-1",
            proposal_ids=[],
            changeset_ids=["cs_recon"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        data = _recovery_snapshot(
            [{"changeset_id": "cs_recon", "status": "needs_review"}], latest=5
        )
        await subscriber._reconcile_recovery(data)

    async with session_factory() as session:
        thread = await get_thread(session, "thread-recon-1")
        assert thread is not None
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_reconcile_recovery_terminal_verdict_dispatches_without_crash(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A terminal approved proposal correlates and attempts a resume gracefully."""
    checkpoints = tmp_path / "cp-recon-verdict.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-recon-2",
            proposal_ids=["prop_recon"],
            changeset_ids=["cs_recon2"],
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        data = _recovery_snapshot(
            [
                {
                    "changeset_id": "cs_recon2",
                    "status": "approved",
                    "approval": {"proposal_id": "prop_recon"},
                }
            ],
            latest=8,
        )
        # Must not raise despite the unreachable worker.
        await subscriber._reconcile_recovery(data)

    async with session_factory() as session:
        thread = await get_thread(session, "thread-recon-2")
        assert thread is not None
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


def test_gate_resume_verdict_maps_applied_as_approved() -> None:
    from ...authoring import VERDICT_APPROVED, VERDICT_REJECTED

    # An AUTO gate resolves-and-applies in one step, so a still-parked run's own
    # proposal reads `applied`; it (and the transient `approved`) resume approved.
    assert _gate_resume_verdict("applied") == VERDICT_APPROVED
    assert _gate_resume_verdict("approved") == VERDICT_APPROVED
    assert _gate_resume_verdict("rejected") == VERDICT_REJECTED
    # A gate still awaiting its verdict carries no decision.
    assert _gate_resume_verdict("needs_review") is None
    assert _gate_resume_verdict("draft") is None


def test_proposal_reconcile_verdict_recovers_missed_request_changes() -> None:
    """A rejected (request_changes'd) proposal is recovered from its approval.

    The exact stall shape (captured live from the engine recovery
    snapshot): a HUMAN edit-proposal reject returns the changeset to ``draft`` -
    the changeset status carries no verdict - but the resolved approval record
    holds ``decision=request_changes``. The reconcile verdict resolver must read
    that approval decision so the parked run resumes into its revision loop rather
    than stalling forever. The prior code (changeset status only) returned ``None``
    here, which was the defect.
    """
    from ...authoring import (
        VERDICT_APPROVED,
        VERDICT_REJECTED,
        VERDICT_REQUEST_CHANGES,
    )

    # Missed request_changes: draft changeset + resolved, non-stale approval.
    assert (
        _proposal_reconcile_verdict(
            {
                "status": "draft",
                "ids": {"proposal:adr"},
                "approval": {
                    "decision": "request_changes",
                    "present": True,
                    "stale": False,
                },
            }
        )
        == VERDICT_REQUEST_CHANGES
    )
    # An edit-proposal reject that lands as a hard `rejected` changeset resolves
    # from the status alone; and an approval `reject` decision maps to rejected.
    assert (
        _proposal_reconcile_verdict(
            {"status": "rejected", "ids": {"proposal:x"}, "approval": None}
        )
        == VERDICT_REJECTED
    )
    assert (
        _proposal_reconcile_verdict(
            {
                "status": "draft",
                "ids": {"proposal:y"},
                "approval": {"decision": "reject", "present": True, "stale": False},
            }
        )
        == VERDICT_REJECTED
    )
    # Terminal changeset status wins first: an applied AUTO gate resumes approved.
    assert (
        _proposal_reconcile_verdict(
            {"status": "applied", "ids": {"proposal:z"}, "approval": None}
        )
        == VERDICT_APPROVED
    )
    # A run genuinely awaiting a human verdict is NOT disturbed: no terminal status
    # and no resolved approval decision.
    assert (
        _proposal_reconcile_verdict(
            {
                "status": "needs_review",
                "ids": {"proposal:pending"},
                "approval": {"present": False},
            }
        )
        is None
    )
    assert (
        _proposal_reconcile_verdict(
            {"status": "draft", "ids": {"proposal:none"}, "approval": None}
        )
        is None
    )
    # A STALE decision (made against a superseded revision) is not acted on.
    assert (
        _proposal_reconcile_verdict(
            {
                "status": "draft",
                "ids": {"proposal:stale"},
                "approval": {
                    "decision": "request_changes",
                    "present": True,
                    "stale": True,
                },
            }
        )
        is None
    )


@pytest.mark.asyncio
async def test_pending_gate_proposal_is_the_current_gate_not_a_stale_one(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The reconcile keys on the CURRENT gate proposal, never a stale earlier one.

    A run accumulates its authoring ids across gates: at the ADR gate its
    authoring_proposal_ids still lists the (applied) research proposal. Correlating
    by any accumulated id would resume the ADR gate on the research verdict and
    complete the run with the ADR unreviewed. The reconcile instead reads
    ``gate_pending_proposal_id`` - the ONE proposal the run is awaiting - so it
    resolves to the ADR proposal, not the stale research one.
    """
    checkpoints = tmp_path / "cp-current-gate.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="thread-adr-gate",
            proposal_ids=["proposal:research", "proposal:adr"],
            changeset_ids=["cs:research", "cs:adr"],
            gate_pending="proposal:adr",
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        pending = await subscriber._thread_pending_gate_proposal("thread-adr-gate")
        assert pending == "proposal:adr"


@pytest.mark.asyncio
async def test_reconcile_parked_runs_noops_when_none_parked_and_throttles(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The steady-state parked-run reconcile is cheap and throttled.

    The AUTO submit-time race recovery runs on every idle cycle, so it must no-op
    when nothing is parked (returning BEFORE contacting the engine - an unreachable
    endpoint would raise if it tried to fetch a snapshot) and must not re-run within
    the throttle window.
    """
    from ...authoring import EngineEndpoint

    checkpoints = tmp_path / "cp-parked-reconcile.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        # An unreachable engine: reached only if the no-parked guard fails.
        endpoint = EngineEndpoint(base_url="http://127.0.0.1:1", bearer_token="tok")

        # Nothing parked -> returns before any engine contact, sets the throttle.
        await subscriber._reconcile_parked_runs(endpoint)
        first_stamp = subscriber._last_parked_reconcile
        assert first_stamp > 0.0

        # An immediate second call is throttled: the stamp does not advance and no
        # engine fetch is attempted.
        await subscriber._reconcile_parked_runs(endpoint)
        assert subscriber._last_parked_reconcile == first_stamp


@pytest.mark.asyncio
async def test_resume_skips_a_superseded_gate_verdict(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Gate-precision: a late verdict for an EARLIER gate is not applied.

    The run has advanced to the ADR gate (gate_pending = ``proposal:adr``) but still
    carries the research gate's proposal id in its ACCUMULATED authoring ids. A late
    research request_changes verdict, matched only by that accumulated id, must NOT
    resume the run - its current gate is not the one the verdict answers, so applying
    it would consume the ADR gate's interrupt with a stale verdict and wedge the run
    at ``next_nodes=[]``. No dispatch occurs and the run stays parked.
    """
    checkpoints = tmp_path / "cp-superseded.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="superseded",
            proposal_ids=["proposal:research", "proposal:adr"],
            changeset_ids=["cs:research", "cs:adr"],
            gate_pending="proposal:adr",
        )
        async with _worker_runtime(checkpointer) as (
            worker_client,
            worker_app,
            _bridge,
        ):
            subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
            await subscriber._resume_with_verdict(
                "superseded", "request_changes", None, {"proposal:research"}
            )
            assert len(worker_app.state.dispatch_ids) == 0
        async with session_factory() as session:
            thread = await get_thread(session, "superseded")
            assert thread is not None
            assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_concurrent_verdict_resumes_elect_one_stable_dispatch(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Real concurrent sessions elect one dispatcher for the same gate verdict.

    Two triggers (e.g. the SSE per-event path and the reconcile sweep) can fire for
    one gate's verdict. Their independent database sessions race through the shared
    journal reservation and lease primitive. Exactly one dispatches, and its HTTP
    dispatch id is the stable identity persisted on the elected journal row.
    """
    checkpoints = tmp_path / "cp-dedup.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="dedup",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
            team_preset="verdict-receipt-preset",
        )
        async with _worker_runtime(
            checkpointer,
            receipt_threads=("dedup",),
        ) as (worker_client, worker_app, _bridge):
            first = _make_subscriber(session_factory, checkpointer, worker_client)
            second = _make_subscriber(session_factory, checkpointer, worker_client)
            await asyncio.gather(
                first._resume_with_verdict(
                    "dedup", "request_changes", None, {"proposal:research"}
                ),
                second._resume_with_verdict(
                    "dedup", "request_changes", None, {"proposal:research"}
                ),
            )
            assert len(worker_app.state.dispatch_ids) == 1
        async with session_factory() as session:
            action = await get_control_action_by_idempotency_key(
                session,
                thread_id="dedup",
                idempotency_key=_verdict_resume_idempotency_key("proposal:research"),
            )
            assert action is not None
            assert action.dispatch_id in worker_app.state.dispatch_ids


@pytest.mark.asyncio
async def test_competing_verdict_payloads_share_request_key_and_dispatch_one(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """One gate request cannot be rebound to a competing verdict payload."""
    checkpoints = tmp_path / "cp-competing-verdicts.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="competing-verdicts",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
            team_preset="verdict-receipt-preset",
        )
        async with _worker_runtime(
            checkpointer,
            receipt_threads=("competing-verdicts",),
        ) as (worker_client, worker_app, _bridge):
            approved = _make_subscriber(session_factory, checkpointer, worker_client)
            rejected = _make_subscriber(session_factory, checkpointer, worker_client)
            await asyncio.gather(
                approved._resume_with_verdict(
                    "competing-verdicts", "approved", "ship", {"proposal:research"}
                ),
                rejected._resume_with_verdict(
                    "competing-verdicts", "rejected", "revise", {"proposal:research"}
                ),
            )
            assert len(worker_app.state.dispatch_ids) == 1
        async with session_factory() as session:
            action = await get_control_action_by_idempotency_key(
                session,
                thread_id="competing-verdicts",
                idempotency_key=_verdict_resume_idempotency_key("proposal:research"),
            )
            assert action is not None
            assert action.request_id == "proposal:research"
            assert json.loads(action.payload_json or "null") in (
                {"verdict": "approved", "notes": "ship"},
                {"verdict": "rejected", "notes": "revise"},
            )


@pytest.mark.asyncio
async def test_expired_verdict_lease_is_redriven(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A still-parked run whose dispatch was lost is re-driven, not orphaned.

    The crash window: a shared journal lease was committed before a dispatch that
    never landed. The run is still parked at the same gate and the lease is expired,
    so the subscriber re-acquires the same action and reuses its stable dispatch id.
    """
    checkpoints = tmp_path / "cp-stale.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="stale",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
            team_preset="verdict-receipt-preset",
        )
        expired_now = (
            datetime.now(UTC) - CONTROL_ACTION_LEASE_TTL - timedelta(seconds=10)
        )
        async with session_factory() as session:
            stale_claim = await claim_control_action(
                session,
                thread_id="stale",
                action_type=ControlActionType.RESUME,
                idempotency_key=_verdict_resume_idempotency_key("proposal:research"),
                request_id="proposal:research",
                payload=_verdict_resume_payload("request_changes", None),
                now=expired_now,
            )
        assert stale_claim.acquired
        async with _worker_runtime(
            checkpointer,
            receipt_threads=("stale",),
        ) as (worker_client, worker_app, _bridge):
            subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
            await subscriber._resume_with_verdict(
                "stale", "request_changes", None, {"proposal:research"}
            )
            assert len(worker_app.state.dispatch_ids) == 1
            assert stale_claim.dispatch_id in worker_app.state.dispatch_ids
