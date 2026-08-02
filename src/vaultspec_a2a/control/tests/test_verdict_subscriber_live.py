"""Live verdict-round-trip proof for the subscriber.

No mocks: exercises the real ``AuthoringClient`` lifecycle stream against a live
dashboard engine on loopback, attached through the shared ``live_engine``
fixture, which resolves the endpoint with the same discovery contract the
subscriber uses in production (``resolve_engine``) and reports an absent engine
through the repository's one external-prerequisite rule - a skip naming the
runbook line, or a failure when the caller declared ``loopback-stack`` present.
``service``-marked and excluded from the default profile. Point
``VAULTSPEC_ENGINE_SERVICE_JSON`` at the engine's discovery file for a
``--no-seat`` workspace-local serve.

What this proves live against the review-outbox engine build
(verified 2026-07-15): a real proposal's full review
round-trip - ``submit_for_review`` publishes ``approval.requested`` (a
non-verdict parking event), and a human decision publishes the verdict event.
Both approve and request-changes ride ``approval.resolved`` (disambiguated only
by the authoritative ``data.decision`` field: ``approve`` vs
``request_changes``); reject rides ``proposal.rejected`` (``decision=reject``).
Each decision payload carries ``{decision, comment, proposal_id, changeset_id,
approval_id, resulting_status, resulting_revision}``. Every frame is replayed
over ``GET /authoring/v1/events`` and decoded by the subscriber's SSE parser;
the verdict + reviewer notes are extracted, and each decision correlates to the
right run seeded into a real ``AsyncSqliteSaver`` checkpoint by its
proposal/changeset id. The end-to-end resume dispatch runs through the real
``safe_dispatch`` path (a real - here unreachable - worker, so no double),
proving the subscriber reaches the resume with no crash; the worker-side landing
of the resumed graph belongs to the phase-gate topology and the service harness,
not this subscriber unit.

The earlier ``session.created``-only limitation is obsolete: the engine now
emits the full proposal/approval lifecycle to the durable outbox. Non-verdict
transitions (e.g. supersede -> ``proposal.updated`` with no ``decision`` field)
remain correctly non-resolving because the decoder keys the decision field
first.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
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

from ...api.tests.clarification_harness import new_state_graph
from ...authoring import (
    AuthoringClient,
    AuthoringResponse,
    AuthoringSession,
    EngineEndpoint,
    LifecycleEvent,
    mint_actor_token,
    verdict_from_event,
)
from ...control.action_lease import claim_control_action
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.event_handlers import relay_event
from ...control.verdict_subscriber import (
    VerdictSubscriber,
    _verdict_resume_idempotency_key,
    _verdict_resume_payload,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
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

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI


@pytest_asyncio.fixture
async def client(live_engine: EngineEndpoint):
    async with AuthoringClient(
        live_engine.base_url, live_engine.bearer_token
    ) as authoring_client:
        yield authoring_client


async def _high_water(client: AuthoringClient) -> int:
    """Read the current outbox high-water so the stream replays only new events."""
    snapshot = await client.recovery_snapshot(last_seq=0)
    assert isinstance(snapshot.data, dict)
    latest = snapshot.data.get("latest_outbox_seq")
    assert isinstance(latest, int)
    return latest


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_stream_decodes_real_lifecycle_event(
    client: AuthoringClient,
) -> None:
    """A real session's outbox event decodes and correlates by its aggregate id."""
    run_id = f"s08-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    assert isinstance(minted.data, dict)
    client._actor_token = minted.data["raw_token"]

    baseline = await _high_water(client)
    session = AuthoringSession(client, run_id)
    created = await session.create_session(scope="repo", title=f"s08 {run_id}")
    assert isinstance(created, AuthoringResponse)
    session_id = session.session_id
    assert session_id is not None

    frames = [frame async for frame in client.stream_lifecycle(last_seq=baseline)]
    lifecycle = [f for f in frames if isinstance(f, LifecycleEvent)]
    assert lifecycle, f"expected lifecycle frames after baseline {baseline}"

    # The real engine wire shape decodes: seq advances, event_kind is a
    # dotted snake_case string, and this run's session id is correlatable.
    mine = [f for f in lifecycle if session_id in f.correlation_ids()]
    assert mine, (
        f"no lifecycle frame correlates to session {session_id}; "
        f"kinds seen: {sorted({f.event_kind for f in lifecycle})}"
    )
    event = mine[0]
    assert event.seq > baseline
    assert "." in event.event_kind
    assert event.aggregate_id == session_id


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_non_verdict_event_does_not_resume(
    client: AuthoringClient,
) -> None:
    """A real non-decision lifecycle event never reads as a reviewer verdict.

    Verdict extraction must resume a run only on an actual review decision. The
    session-lifecycle events observable on this engine build are not verdicts, so
    every decoded frame must yield no verdict.
    """
    run_id = f"s08-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    assert isinstance(minted.data, dict)
    client._actor_token = minted.data["raw_token"]

    baseline = await _high_water(client)
    session = AuthoringSession(client, run_id)
    created = await session.create_session(scope="repo", title=f"s08 {run_id}")
    assert isinstance(created, AuthoringResponse)

    frames = [frame async for frame in client.stream_lifecycle(last_seq=baseline)]
    lifecycle = [f for f in frames if isinstance(f, LifecycleEvent)]
    assert lifecycle, "expected lifecycle frames for the created session"
    assert all(verdict_from_event(f) is None for f in lifecycle)


# ---------------------------------------------------------------------------
# Full verdict round-trip: real engine proposal -> submit -> human decision ->
# subscriber correlation + resume dispatch. No mocks anywhere.
# ---------------------------------------------------------------------------

# Wire decision (payload ``ReviewDecisionKind``) -> envelope ``CommandKind``.
_ENVELOPE_COMMAND = {"approve": "approve", "reject": "reject", "edit": "edit_proposal"}


def _whole_document_op(run_id: str, label: str) -> dict[str, Any]:
    return {
        "child_key": f"research/{label}-{run_id}.md",
        "operation": "create_document",
        "target": {
            "document": {
                "kind": "provisional_create",
                "provisional_doc_id": f"prov:{label}:{run_id}",
                "doc_type": "research",
                "feature": "a2a-edge-conformance",
                "title": f"{label} round-trip",
                "collision_status": "available",
            }
        },
        "draft": {"mode": "whole_document", "body": f"# {label}\n\nbody."},
    }


async def _submit_proposal(
    session: AuthoringSession, run_id: str, label: str
) -> dict[str, str]:
    """Create + submit a proposal; return its correlation ids and reviewed rev."""
    changeset_id = session.new_changeset_id(label)
    created = await session.create_proposal(
        changeset_id=changeset_id,
        summary=label,
        operations=[_whole_document_op(run_id, label)],
    )
    assert isinstance(created, AuthoringResponse)
    revision = created.data["changeset_revision"]
    submitted = await session.submit(
        changeset_id=changeset_id, expected_revision=revision, summary=f"{label} submit"
    )
    assert isinstance(submitted, AuthoringResponse)
    approval = submitted.data["approval"]
    return {
        "changeset_id": changeset_id,
        "approval_id": approval["approval_id"],
        "proposal_id": approval["proposal_id"],
        "reviewed_revision": approval["reviewed"]["proposal_revision"],
    }


async def _decide(
    client: AuthoringClient,
    reviewer_token: str,
    info: dict[str, str],
    wire_decision: str,
    comment: str,
    run_id: str,
    label: str,
) -> None:
    """Submit a human review decision through the real decision endpoint."""
    result = await client.post_command(
        f"/v1/reviews/{info['approval_id']}/decisions",
        command=_ENVELOPE_COMMAND[wire_decision],
        payload={
            "proposal_id": info["proposal_id"],
            "approval_id": info["approval_id"],
            "decision": wire_decision,
            "reviewed_revision": info["reviewed_revision"],
            "comment": comment,
        },
        idempotency_key=f"idk-dec-{label}-{run_id}",
        actor_token=reviewer_token,
    )
    assert isinstance(result, AuthoringResponse)


async def _seed_parked(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    proposal_id: str,
    changeset_id: str,
) -> None:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    checkpoint["channel_values"]["authoring_proposal_ids"] = [proposal_id]
    checkpoint["channel_values"]["authoring_changeset_ids"] = [changeset_id]
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


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_verdict_round_trip_parks_and_resumes(
    client: AuthoringClient, tmp_path
) -> None:
    """Approve / reject / request_changes each resume the correct parked run.

    Drives three real proposals through submit + human decision, then feeds the
    real outbox frames through the subscriber: ``approval.requested`` parks (no
    verdict), and each decision frame yields the pinned verdict + reviewer notes
    and correlates to the run seeded for that proposal. The subscriber's real
    resume-dispatch path is exercised end to end against an unreachable worker
    (genuine failure handling, no double).
    """
    # --- engine side: agent proposes, human decides ---
    run_id = f"rt-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    client._actor_token = minted.data["raw_token"]

    baseline = await _high_water(client)
    session = AuthoringSession(client, run_id)
    await session.create_session(scope="repo", title=run_id)
    reviewer = await mint_actor_token(client, actor_id=f"human:{run_id}", kind="human")
    assert isinstance(reviewer, AuthoringResponse)
    reviewer_token = reviewer.data["raw_token"]

    approve = await _submit_proposal(session, run_id, "appr")
    reject = await _submit_proposal(session, run_id, "rej")
    changes = await _submit_proposal(session, run_id, "edit")

    await _decide(client, reviewer_token, approve, "approve", "ship it", run_id, "appr")
    await _decide(client, reviewer_token, reject, "reject", "not yet", run_id, "rej")
    await _decide(client, reviewer_token, changes, "edit", "tighten it", run_id, "edit")

    # --- a2a side: seed a parked run per proposal on a real checkpointer ---
    db_file = tmp_path / "rt.db"
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints = tmp_path / "rt-cp.db"

    async with (
        AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer,
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
    ):
        await checkpointer.setup()
        seeds = {
            "approved": ("thread-appr", approve),
            "rejected": ("thread-rej", reject),
            "request_changes": ("thread-edit", changes),
        }
        for _verdict, (thread_id, info) in seeds.items():
            await _seed_parked(
                session_factory,
                checkpointer,
                thread_id=thread_id,
                proposal_id=info["proposal_id"],
                changeset_id=info["changeset_id"],
            )

        subscriber = VerdictSubscriber(
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

        frames = [f async for f in client.stream_lifecycle(last_seq=baseline)]
        lifecycle = [f for f in frames if isinstance(f, LifecycleEvent)]

        # (a) submit publishes approval.requested, which never reads as a verdict.
        requested = [f for f in lifecycle if f.event_kind == "approval.requested"]
        assert len(requested) >= 3, "each submit must park via approval.requested"
        assert all(verdict_from_event(f) is None for f in requested)

        # (b) each decision frame carries the pinned verdict + notes, rides its
        #     expected event kind, and correlates to the run seeded for that
        #     proposal. Approve and request-changes both ride approval.resolved
        #     (decision-field disambiguated); reject rides proposal.rejected.
        expected = {
            "approved": (approve, "ship it", "approval.resolved"),
            "rejected": (reject, "not yet", "proposal.rejected"),
            "request_changes": (changes, "tighten it", "approval.resolved"),
        }
        matched: dict[str, str] = {}
        for frame in lifecycle:
            verdict = verdict_from_event(frame)
            if verdict is None:
                continue
            verdict_kind, notes = verdict
            info, want_notes, want_kind = expected[verdict_kind]
            assert notes == want_notes, f"{verdict_kind}: notes {notes!r}"
            assert frame.event_kind == want_kind, (
                f"{verdict_kind} rode {frame.event_kind}, expected {want_kind}"
            )
            assert info["proposal_id"] in frame.correlation_ids()
            thread_id = await subscriber._find_parked_thread(frame.correlation_ids())
            assert thread_id is not None
            assert thread_id == seeds[verdict_kind][0]
            matched[verdict_kind] = thread_id
            # Full path: correlate + dispatch (unreachable worker, graceful).
            await subscriber._process_event(frame)

        assert set(matched) == {"approved", "rejected", "request_changes"}

    await db_engine.dispose()


async def _seed_parked_gate(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    proposal_id: str,
    changeset_id: str,
    status: ThreadStatus = ThreadStatus.INPUT_REQUIRED,
    team_preset: str | None = None,
) -> None:
    """Seed a run parked at ``proposal_id``'s gate (with its durable row).

    Mirrors what the phase submit node commits before the gate parks:
    ``gate_pending_proposal_id`` is the ONE proposal the run awaits a verdict for,
    and a durable ``document_approval_request`` permission row records the pause.

    ``status`` defaults to ``INPUT_REQUIRED`` (the healthy parked posture); pass
    ``RUNNING`` to model the clobber, where a prior gate's verdict resume
    left the run mis-statused RUNNING even though its checkpoint is parked at the
    gate - the case the reconcile must still recover by checkpoint truth.
    """
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{thread_id}"
    checkpoint["channel_values"]["authoring_proposal_ids"] = [proposal_id]
    checkpoint["channel_values"]["authoring_changeset_ids"] = [changeset_id]
    checkpoint["channel_values"]["gate_pending_proposal_id"] = proposal_id
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
        await update_thread_status(session, thread_id, status)
        await record_permission_request(
            session,
            request_id=f"{thread_id}:adr-gate",
            thread_id=thread_id,
            pause_reason_type="document_approval_request",
            description="Approve the ADR document",
            allowed_options=[
                {"option_id": "approve", "name": "Approve", "kind": "allow_once"}
            ],
        )
        await session.commit()


def _install_receipt_graph(
    executor: Executor,
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> None:
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
    bridge = WorkerBridge("http://127.0.0.1:1", "verdict-live-receipt-test")
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
    *,
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
                if not isinstance(candidate, dict):
                    continue
                receipt = cast("dict[str, object]", candidate)
                if (
                    receipt.get("type") == "dispatch_applied"
                    and receipt.get("dispatch_id") == dispatch_id
                ):
                    return receipt
            await anyio.sleep(0.01)


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_missed_reject_is_recovered_by_parked_reconcile(
    client: AuthoringClient, live_engine: EngineEndpoint, tmp_path
) -> None:
    """A HUMAN reject consumed BEFORE the run parks is recovered by the reconcile.

    The stall reproduced end to end with no mocks: a real proposal is
    submitted and a human ``edit`` (request_changes) decision is applied, which
    returns the changeset to ``draft`` - so the changeset status carries no verdict
    and only the resolved approval record holds ``decision=request_changes``. The
    reject event is NEVER fed through the per-event path (modelling the submit-time
    race that consumed it before the run became INPUT_REQUIRED). The steady-state
    parked-run reconcile must then read the approval decision off the real engine
    recovery snapshot, correlate it to the parked run by its
    ``gate_pending_proposal_id``, and re-dispatch a ``resume`` carrying
    ``verdict=request_changes`` to the worker - routing the run back into its
    revision loop instead of stalling forever.

    The worker is the real worker app with a real Executor, checkpointer, and bridge.
    Its HTTP acknowledgement proves scheduling only; the exact application receipt
    resolves the answered gate and returns the thread to RUNNING.
    """
    # --- engine side: agent proposes, human rejects via edit (request_changes) ---
    run_id = f"mr-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    client._actor_token = minted.data["raw_token"]

    session = AuthoringSession(client, run_id)
    await session.create_session(scope="repo", title=run_id)
    reviewer = await mint_actor_token(client, actor_id=f"human:{run_id}", kind="human")
    assert isinstance(reviewer, AuthoringResponse)
    reviewer_token = reviewer.data["raw_token"]

    info = await _submit_proposal(session, run_id, "adr")
    await _decide(
        client, reviewer_token, info, "edit", "tighten the rationale", run_id, "adr"
    )

    # The reject leaves the changeset non-terminal (draft) with a resolved,
    # non-stale approval decision - the exact recovery signal the reconcile reads.
    snapshot = await client.recovery_snapshot(last_seq=0)
    assert isinstance(snapshot.data, dict)
    proposals = snapshot.data["snapshot"]["proposals"]["items"]
    mine = [p for p in proposals if p.get("changeset_id") == info["changeset_id"]]
    assert mine, "submitted changeset absent from the recovery snapshot"
    rejected = mine[0]
    assert rejected["status"] == "draft"
    assert rejected["approval"]["decision"] == "request_changes"
    assert rejected["approval"]["stale"] is False

    # --- a2a side: seed the parked run, NEVER processing the reject event ---
    db_file = tmp_path / "mr.db"
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints = tmp_path / "mr-cp.db"
    thread_id = f"thread-{run_id}"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await checkpointer.setup()
        await _seed_parked_gate(
            session_factory,
            checkpointer,
            thread_id=thread_id,
            proposal_id=info["proposal_id"],
            changeset_id=info["changeset_id"],
            team_preset="verdict-receipt-preset",
        )
        async with _worker_runtime(checkpointer, receipt_threads=(thread_id,)) as (
            worker_client,
            worker_app,
            bridge,
        ):
            subscriber = VerdictSubscriber(
                session_factory=session_factory,
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30.0
                ),
                worker_spawner=LazyWorkerSpawner(
                    worker_url="http://worker", worker_port=1, auto_spawn=False
                ),
                endpoint_provider=lambda: live_engine,
                recursion_limit=25,
            )

            await subscriber._reconcile_parked_runs(live_engine)

            assert len(worker_app.state.dispatch_ids) == 1
            async with session_factory() as db:
                action = await get_control_action_by_idempotency_key(
                    db,
                    thread_id=thread_id,
                    idempotency_key=_verdict_resume_idempotency_key(
                        info["proposal_id"]
                    ),
                )
                gate_row = await get_permission_request(db, f"{thread_id}:adr-gate")
                thread = await get_thread(db, thread_id)
            assert action is not None
            assert action.dispatch_id in worker_app.state.dispatch_ids
            assert action.applied_at is None
            assert gate_row is not None
            assert gate_row.request_status == PermissionRequestStatus.PENDING.value
            assert thread is not None
            assert thread.status == ThreadStatus.INPUT_REQUIRED.value

            receipt = await _wait_for_receipt(bridge, dispatch_id=action.dispatch_id)
            await relay_event(thread_id, receipt, session_factory=session_factory)

            async with session_factory() as db:
                gate_row = await get_permission_request(db, f"{thread_id}:adr-gate")
                thread = await get_thread(db, thread_id)
            assert gate_row is not None
            assert gate_row.request_status == PermissionRequestStatus.APPLIED.value
            assert thread is not None
            assert thread.status == ThreadStatus.RUNNING.value

    await db_engine.dispose()


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_running_clobbered_parked_run_is_recovered_by_parked_reconcile(
    client: AuthoringClient, live_engine: EngineEndpoint, tmp_path
) -> None:
    """A run parked at a gate but mis-statused RUNNING is still recovered.

    The recovery_required wedge: a run's checkpoint is parked at a gate awaiting a
    verdict, but its thread status is RUNNING rather than INPUT_REQUIRED - because a
    a prior receipt settlement set RUNNING and that write raced AFTER the next
    gate's permission event set INPUT_REQUIRED, or that gate's permission event
    never landed. Keyed on ``thread.status`` alone
    the reconcile would never see such a run, so its decided verdict is never
    delivered and NOTHING re-drives it - the run stalls forever while run-status
    projects ``recovery_required`` off the checkpoint-vs-durable gap.

    This is the same live round-trip as the missed-reject test, differing ONLY in
    the seeded status: the parked run is RUNNING (the clobber), and the reconcile -
    keyed on CHECKPOINT truth (``gate_pending_proposal_id`` + the engine's decided
    approval decision) rather than the derived status - must still correlate it and
    re-dispatch exactly one ``resume`` carrying the missed ``request_changes``.
    """
    run_id = f"cl-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    client._actor_token = minted.data["raw_token"]

    session = AuthoringSession(client, run_id)
    await session.create_session(scope="repo", title=run_id)
    reviewer = await mint_actor_token(client, actor_id=f"human:{run_id}", kind="human")
    assert isinstance(reviewer, AuthoringResponse)
    reviewer_token = reviewer.data["raw_token"]

    info = await _submit_proposal(session, run_id, "adr")
    await _decide(
        client, reviewer_token, info, "edit", "tighten the rationale", run_id, "adr"
    )

    # The reject leaves the changeset non-terminal (draft) with a resolved,
    # non-stale approval decision - the exact recovery signal the reconcile reads.
    snapshot = await client.recovery_snapshot(last_seq=0)
    assert isinstance(snapshot.data, dict)
    proposals = snapshot.data["snapshot"]["proposals"]["items"]
    mine = [p for p in proposals if p.get("changeset_id") == info["changeset_id"]]
    assert mine, "submitted changeset absent from the recovery snapshot"
    assert mine[0]["status"] == "draft"
    assert mine[0]["approval"]["decision"] == "request_changes"
    assert mine[0]["approval"]["stale"] is False

    db_file = tmp_path / "cl.db"
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints = tmp_path / "cl-cp.db"
    thread_id = f"thread-{run_id}"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await checkpointer.setup()
        # The distinguishing seed: parked in the checkpoint, but RUNNING in the DB.
        await _seed_parked_gate(
            session_factory,
            checkpointer,
            thread_id=thread_id,
            proposal_id=info["proposal_id"],
            changeset_id=info["changeset_id"],
            status=ThreadStatus.RUNNING,
            team_preset="verdict-receipt-preset",
        )
        async with _worker_runtime(checkpointer, receipt_threads=(thread_id,)) as (
            worker_client,
            worker_app,
            bridge,
        ):
            subscriber = VerdictSubscriber(
                session_factory=session_factory,
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30.0
                ),
                worker_spawner=LazyWorkerSpawner(
                    worker_url="http://worker", worker_port=1, auto_spawn=False
                ),
                endpoint_provider=lambda: live_engine,
                recursion_limit=25,
            )

            await subscriber._reconcile_parked_runs(live_engine)

            assert len(worker_app.state.dispatch_ids) == 1
            async with session_factory() as db:
                action = await get_control_action_by_idempotency_key(
                    db,
                    thread_id=thread_id,
                    idempotency_key=_verdict_resume_idempotency_key(
                        info["proposal_id"]
                    ),
                )
            assert action is not None
            assert action.applied_at is None
            receipt = await _wait_for_receipt(bridge, dispatch_id=action.dispatch_id)
            await relay_event(thread_id, receipt, session_factory=session_factory)
            async with session_factory() as db:
                settled = await get_control_action_by_idempotency_key(
                    db,
                    thread_id=thread_id,
                    idempotency_key=_verdict_resume_idempotency_key(
                        info["proposal_id"]
                    ),
                )
            assert settled is not None
            assert settled.applied_at is not None

    await db_engine.dispose()


@pytest.mark.service
@pytest.mark.asyncio
async def test_live_running_with_fresh_resume_claim_is_not_re_driven(
    client: AuthoringClient, live_engine: EngineEndpoint, tmp_path
) -> None:
    """The broadened RUNNING candidacy does NOT false-re-drive an in-flight resume.

    Guard: including RUNNING threads in the reconcile candidate set must not
    double-drive a run whose resume is legitimately already in flight. The
    control-action lease taken by ``_resume_with_verdict`` is the observable
    proof-of-in-flight: a RUNNING run parked at a gate WITH a decided verdict on the
    engine AND a live lease on that exact gate's typed verdict is a run whose resume
    was just dispatched and has not yet advanced the checkpoint - re-dispatching
    would be the false re-drive. The reconcile must correlate it (RUNNING is now a
    candidate) yet dispatch NOTHING, because losing the lease election
    short-circuits the per-thread resume.

    Same real round-trip as the recovery tests (real engine decision, real DB, real
    checkpointer, real worker app), differing only in the seeded live lease
    and the zero-dispatch assertion. Lease EXPIRY - the re-drivable case that stops
    a lost dispatch orphaning a run - is owned by the action-lease tests, which is
    where the TTL itself lives.
    """
    run_id = f"fc-{uuid.uuid4().hex[:8]}"
    minted = await mint_actor_token(client, actor_id=f"agent:{run_id}", kind="agent")
    assert isinstance(minted, AuthoringResponse)
    client._actor_token = minted.data["raw_token"]

    session = AuthoringSession(client, run_id)
    await session.create_session(scope="repo", title=run_id)
    reviewer = await mint_actor_token(client, actor_id=f"human:{run_id}", kind="human")
    assert isinstance(reviewer, AuthoringResponse)
    reviewer_token = reviewer.data["raw_token"]

    info = await _submit_proposal(session, run_id, "adr")
    await _decide(
        client, reviewer_token, info, "edit", "tighten the rationale", run_id, "adr"
    )

    db_file = tmp_path / "fc.db"
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    checkpoints = tmp_path / "fc-cp.db"
    thread_id = f"thread-{run_id}"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints)) as checkpointer:
        await checkpointer.setup()
        await _seed_parked_gate(
            session_factory,
            checkpointer,
            thread_id=thread_id,
            proposal_id=info["proposal_id"],
            changeset_id=info["changeset_id"],
            status=ThreadStatus.RUNNING,
        )
        # A FRESH lease on the exact current gate: a resume is already in flight.
        # Claimed through the production verb with the production key and payload,
        # so this is the same journal row a real in-flight resume would hold - not
        # a hand-shaped stand-in the subscriber might read differently.
        async with session_factory() as db:
            seeded = await claim_control_action(
                db,
                thread_id=thread_id,
                action_type=ControlActionType.RESUME,
                idempotency_key=_verdict_resume_idempotency_key(info["proposal_id"]),
                request_id=info["proposal_id"],
                payload=_verdict_resume_payload("request_changes", None),
            )
        # Sanity: the seed genuinely OWNS the lease, so the subscriber's own claim
        # loses to a live owner rather than to an already-applied or absent row.
        assert seeded.acquired, "seeded lease did not acquire the in-flight resume"
        assert seeded.claim_token is not None

        async with _worker_runtime(checkpointer) as (
            worker_client,
            worker_app,
            _bridge,
        ):
            subscriber = VerdictSubscriber(
                session_factory=session_factory,
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30.0
                ),
                worker_spawner=LazyWorkerSpawner(
                    worker_url="http://worker", worker_port=1, auto_spawn=False
                ),
                endpoint_provider=lambda: live_engine,
                recursion_limit=25,
            )

            await subscriber._reconcile_parked_runs(live_engine)

            # The fresh claim short-circuited the resume: NO false re-drive.
            assert len(worker_app.state.dispatch_ids) == 0

    await db_engine.dispose()
