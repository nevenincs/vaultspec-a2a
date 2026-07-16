"""Integration tests for the verdict subscriber's correlation and cursor paths.

Real aiosqlite database and a real LangGraph ``AsyncSqliteSaver`` checkpointer,
no mocks. These cover the two internals that do not require the engine or the
worker: correlating an inbound verdict's ids to a parked run through its
checkpointed ``TeamState`` references, and the durable cursor that survives a
gateway restart. The engine-facing SSE consumption is proved live in
``test_verdict_subscriber_live``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette
    from starlette.requests import Request

from vaultspec_a2a.authoring import AuthoringClient, LifecycleEvent, StreamError
from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.verdict_subscriber import (
    _RESUME_CLAIM_TTL_SECONDS,
    VerdictSubscriber,
    _gate_resume_verdict,
    _iter_recovery_proposals,
    _proposal_reconcile_verdict,
    _recovery_high_water,
    _StreamInterruptedError,
    _with_resume_claim,
)
from vaultspec_a2a.control.worker_management import LazyWorkerSpawner
from vaultspec_a2a.database import (
    create_thread,
    get_authoring_cursor,
    get_permission_request,
    get_thread,
    record_permission_request,
    update_thread_metadata,
    update_thread_status,
)
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.thread.enums import PermissionRequestStatus, ThreadStatus


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


async def _seed_parked_thread(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    proposal_ids: list[str],
    changeset_ids: list[str],
    gate_pending: str | None = None,
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
        await create_thread(session, thread_id=thread_id)
        await update_thread_status(session, thread_id, ThreadStatus.INPUT_REQUIRED)
        await session.commit()


@pytest.mark.asyncio
async def test_resume_resolves_the_answered_document_gate_permission_row(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A subscriber-driven resume resolves the answered gate's durable row (GAP D).

    The document gate parks with a durable ``document_approval_request`` permission
    row; the verdict subscriber resumes the run past it via ``Command(resume)``,
    bypassing the permission-response FSM. If the row were left pending it would be
    stranded once the checkpoint interrupt it belonged to is gone, and run-status -
    the authoritative recovery read - would assert ``recovery_required`` and mask
    the real ``awaiting_adr_decision`` phase. On a successful resume the row is
    marked applied; a co-resident tool-permission row (a different pause reason) is
    left untouched, and the thread returns to RUNNING.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def _accept_dispatch(_request: object) -> JSONResponse:
        return JSONResponse({"status": "dispatched"})

    worker_app = Starlette(
        routes=[Route("/dispatch", _accept_dispatch, methods=["POST"])]
    )
    thread_id = "gate-resume"
    checkpoints = tmp_path / "cp-resume.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=worker_app),
            base_url="http://worker",
        ) as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id=thread_id,
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
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

        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        await subscriber._resume_with_verdict(
            thread_id, "approved", None, {"proposal:research"}
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
    from vaultspec_a2a.authoring import VERDICT_APPROVED, VERDICT_REJECTED

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

    The exact P04.S10 stall shape (captured live from the engine recovery
    snapshot): a HUMAN edit-proposal reject returns the changeset to ``draft`` -
    the changeset status carries no verdict - but the resolved approval record
    holds ``decision=request_changes``. The reconcile verdict resolver must read
    that approval decision so the parked run resumes into its revision loop rather
    than stalling forever. The prior code (changeset status only) returned ``None``
    here, which was the defect.
    """
    from vaultspec_a2a.authoring import (
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
    from vaultspec_a2a.authoring import EngineEndpoint

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


def _recording_worker() -> tuple[Starlette, list[dict[str, object]]]:
    """A worker app recording each dispatch POST; returns ``(app, calls)``."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    calls: list[dict[str, object]] = []

    async def _accept(request: Request) -> JSONResponse:
        calls.append(await request.json())
        return JSONResponse({"status": "dispatched"})

    return Starlette(routes=[Route("/dispatch", _accept, methods=["POST"])]), calls


@pytest.mark.asyncio
async def test_resume_skips_a_superseded_gate_verdict(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Gate-precision: a late verdict for an EARLIER gate is not applied (P04.S10).

    The run has advanced to the ADR gate (gate_pending = ``proposal:adr``) but still
    carries the research gate's proposal id in its ACCUMULATED authoring ids. A late
    research request_changes verdict, matched only by that accumulated id, must NOT
    resume the run - its current gate is not the one the verdict answers, so applying
    it would consume the ADR gate's interrupt with a stale verdict and wedge the run
    at ``next_nodes=[]``. No dispatch occurs and the run stays parked (e106b7a).
    """
    app, calls = _recording_worker()
    checkpoints = tmp_path / "cp-superseded.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="superseded",
            proposal_ids=["proposal:research", "proposal:adr"],
            changeset_ids=["cs:research", "cs:adr"],
            gate_pending="proposal:adr",
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        await subscriber._resume_with_verdict(
            "superseded", "request_changes", None, {"proposal:research"}
        )
        assert calls == []
        async with session_factory() as session:
            thread = await get_thread(session, "superseded")
            assert thread is not None
            assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_fresh_resume_claim_dedups_double_dispatch(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A second trigger for the SAME gate skips on the fresh claim (P04.S10).

    Two triggers (e.g. the SSE per-event path and the reconcile sweep) can fire for
    one gate's verdict. The first writes a durable claim before dispatch; the second,
    reading a fresh claim on the same gate, skips - so the gate is resumed exactly
    once and the checkpoint's interrupt lineage is never double-consumed.
    """
    app, calls = _recording_worker()
    checkpoints = tmp_path / "cp-dedup.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="dedup",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        await subscriber._resume_with_verdict(
            "dedup", "request_changes", None, {"proposal:research"}
        )
        await subscriber._resume_with_verdict(
            "dedup", "request_changes", None, {"proposal:research"}
        )
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_stale_resume_claim_is_redriven(
    tmp_path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A still-parked run whose dispatch was lost is re-driven, not orphaned.

    The crash window: a claim was written before a dispatch that never landed (the
    process died or the dispatch failed between claim and resume). The run is still
    parked at the same gate and the claim is now older than the TTL, so the next
    trigger legitimately re-drives it - a lost dispatch is retried, not permanently
    stranded. This is the liveness half of the idempotent-with-retry invariant: the
    durable-before-dispatch marker must never convert the double-dispatch hole into
    a lost-dispatch hole.
    """
    app, calls = _recording_worker()
    checkpoints = tmp_path / "cp-stale.db"
    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as worker_client,
    ):
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            thread_id="stale",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
        )
        stale_ts = time.time() - _RESUME_CLAIM_TTL_SECONDS - 10.0
        async with session_factory() as session:
            await update_thread_metadata(
                session,
                "stale",
                _with_resume_claim(None, "proposal:research", stale_ts),
            )
            await session.commit()
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        await subscriber._resume_with_verdict(
            "stale", "request_changes", None, {"proposal:research"}
        )
        assert len(calls) == 1
