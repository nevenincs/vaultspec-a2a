"""Integration tests for the verdict subscriber's correlation and cursor paths.

Real aiosqlite database and a real LangGraph ``AsyncSqliteSaver`` checkpointer,
no mocks. These cover the two internals that do not require the engine or the
worker: correlating an inbound verdict's ids to a parked run through its pending
document-approval row, and the durable cursor that survives a gateway restart.
The engine-facing SSE consumption is proved live in
``test_verdict_subscriber_live``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from ...tests._checkpoint_seeding import real_checkpoint
from ...tests._write_authority import make_test_write_authority

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
    )

from ...authoring import AuthoringClient, LifecycleEvent, StreamError
from ...control._verdict_subscriber_config import VerdictSubscriberConfig
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.execution_authority import resolve_execution_authority
from ...control.verdict_subscriber import (
    VerdictSubscriber,
    _gate_resume_verdict,
    _iter_recovery_proposals,
    _proposal_reconcile_verdict,
    _recovery_high_water,
    _StreamInterruptedError,
)
from ...database import (
    create_thread,
    get_authoring_cursor,
    get_control_action_by_idempotency_key,
    get_thread,
    mark_permission_request_applied,
    pending_document_approval_thread,
    record_permission_request,
)
from ...team.team_config import load_team_config
from ...testing import (
    DEFAULT_TEAM_PRESET,
    adopted_spawner,
    current_execution_metadata,
    seed_create_action,
    served_worker,
)
from ...thread.enums import ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.idempotency import authoring_verdict_action_key

_TEST_INTERNAL_TOKEN = "verdict-subscriber-test-token"


def _make_subscriber(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    worker_client: httpx.AsyncClient,
) -> VerdictSubscriber:
    """Construct a subscriber with real (unused-in-correlation) dispatch deps."""
    return VerdictSubscriber(
        VerdictSubscriberConfig(
            session_factory=session_factory,
            checkpointer=checkpointer,
            worker_client=worker_client,
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=3, recovery_timeout=30.0
            ),
            worker_spawner=adopted_spawner(),
            endpoint_provider=lambda: None,
        )
    )


@dataclass(frozen=True, slots=True)
class _ParkedThreadSeed:
    """Checkpoint and thread values used to seed one parked run."""

    thread_id: str
    proposal_ids: list[str]
    changeset_ids: list[str]
    gate_pending: str | None = None
    team_preset: str | None = None
    status: ThreadStatus = ThreadStatus.INPUT_REQUIRED


async def _seed_parked_thread(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    seed: _ParkedThreadSeed,
) -> None:
    """Create a thread, parked unless seeded otherwise, with authoring-id checkpoint.

    A ``gate_pending`` proposal also records the gate's pending
    ``document_approval_request`` row under that proposal id, as the gate's
    park does.
    """
    thread_id = seed.thread_id
    proposal_ids = seed.proposal_ids
    changeset_ids = seed.changeset_ids
    workspace = Path.cwd()
    metadata = current_execution_metadata(workspace)
    execution_authority = resolve_execution_authority(metadata)
    definition = (
        freeze_graph_definition(
            load_team_config(seed.team_preset, workspace_root=workspace),
            workspace_root=workspace,
        )
        if seed.team_preset is not None
        else None
    )
    await checkpointer.setup()
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""}
    }
    checkpoint = await real_checkpoint()
    checkpoint["channel_values"]["authoring_proposal_ids"] = proposal_ids
    checkpoint["channel_values"]["authoring_changeset_ids"] = changeset_ids
    if seed.gate_pending is not None:
        checkpoint["channel_values"]["gate_pending_proposal_id"] = seed.gate_pending
    if definition is not None:
        checkpoint["channel_values"]["model_assignment_digest"] = (
            execution_authority.model_assignment_digest
        )
        checkpoint["channel_values"]["graph_definition_digest"] = definition.digest()
    await checkpointer.aput(
        config,
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            team_preset=seed.team_preset,
            metadata=metadata,
            status=seed.status,
        )
        if seed.team_preset is not None:
            await seed_create_action(
                session,
                thread_id,
                workspace=workspace,
                team_preset=seed.team_preset,
            )
        if seed.gate_pending is not None:
            await record_permission_request(
                session,
                request_id=seed.gate_pending,
                thread_id=thread_id,
                pause_reason_type="document_approval_request",
                description="Approve the document",
                allowed_options=[
                    {"option_id": "approve", "name": "Approve", "kind": "allow_once"}
                ],
            )
        await session.commit()


@pytest.mark.asyncio
async def test_correlates_parked_thread_by_its_pending_gate_request(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="thread-parked-1",
            proposal_ids=["prop_abc"],
            changeset_ids=["cs_abc"],
            gate_pending="prop_abc",
        ),
    )
    async with session_factory() as session:
        matched = await pending_document_approval_thread(
            session, request_ids={"approval_abc", "prop_abc"}
        )
    assert matched == "thread-parked-1"


@pytest.mark.asyncio
async def test_only_the_gate_proposal_correlates(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A changeset id alone reaches no run: the gate parks on its proposal."""
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="thread-parked-2",
            proposal_ids=["prop_xyz"],
            changeset_ids=["cs_xyz"],
            gate_pending="prop_xyz",
        ),
    )
    async with session_factory() as session:
        assert (
            await pending_document_approval_thread(
                session, request_ids={"cs_xyz", "unrelated"}
            )
            is None
        )
        matched = await pending_document_approval_thread(
            session, request_ids={"cs_xyz", "prop_xyz"}
        )
    assert matched == "thread-parked-2"


@pytest.mark.asyncio
async def test_unknown_ids_correlate_to_nothing(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="thread-parked-3",
            proposal_ids=["prop_known"],
            changeset_ids=["cs_known"],
            gate_pending="prop_known",
        ),
    )
    async with session_factory() as session:
        assert (
            await pending_document_approval_thread(
                session, request_ids={"prop_missing"}
            )
            is None
        )


@pytest.mark.asyncio
async def test_non_parked_thread_is_not_correlated(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A RUNNING thread is not a gate-parked candidate even with a pending row."""
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="thread-running",
            proposal_ids=["prop_running"],
            changeset_ids=[],
            gate_pending="prop_running",
            status=ThreadStatus.RUNNING,
        ),
    )
    async with session_factory() as session:
        assert (
            await pending_document_approval_thread(
                session, request_ids={"prop_running"}
            )
            is None
        )


@pytest.mark.asyncio
async def test_settled_gate_request_is_not_correlated(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A replayed verdict for an applied gate finds no run to resume."""
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="thread-settled",
            proposal_ids=["prop_settled"],
            changeset_ids=[],
            gate_pending="prop_settled",
        ),
    )
    async with session_factory() as session:
        await mark_permission_request_applied(session, request_id="prop_settled")
        await session.commit()
        assert (
            await pending_document_approval_thread(
                session, request_ids={"prop_settled"}
            )
            is None
        )


@pytest.mark.asyncio
async def test_cursor_advances_and_survives_restart(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """The durable cursor a restarted subscriber reads is the last it advanced."""
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
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


def _recovery_snapshot(
    items: list[dict[str, object]], *, latest: int
) -> dict[str, object]:
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
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        client = AuthoringClient("http://127.0.0.1:1", "tok")
        frame = StreamError(error_kind="authoring_store_unavailable", error="down")
        with pytest.raises(_StreamInterruptedError):
            await subscriber._process_frame(client, frame)
        await client.aclose()


@pytest.mark.asyncio
async def test_process_frame_advances_cursor_for_non_verdict_event(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A non-verdict lifecycle frame advances the cursor without dispatching."""
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
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
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            _ParkedThreadSeed(
                thread_id="thread-noverdict",
                proposal_ids=["prop_nv"],
                changeset_ids=[],
            ),
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
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A real verdict correlates and dispatches; an unreachable worker is handled.

    The dispatch goes to a real worker client on a dead port, so ``safe_dispatch``
    exercises genuine ``WorkerUnreachableError`` handling (no double). The run
    stays parked because the resume never landed.
    """
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            _ParkedThreadSeed(
                thread_id="thread-verdict",
                proposal_ids=["prop_v"],
                changeset_ids=[],
                gate_pending="prop_v",
            ),
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
async def test_gap_reconcile_no_verdict_status_is_a_noop(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            _ParkedThreadSeed(
                thread_id="thread-recon-1",
                proposal_ids=["prop_recon1"],
                changeset_ids=["cs_recon"],
                gate_pending="prop_recon1",
            ),
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        data = _recovery_snapshot(
            [
                {
                    "changeset_id": "cs_recon",
                    "status": "needs_review",
                    "approval": {"proposal_id": "prop_recon1"},
                }
            ],
            latest=5,
        )
        await subscriber._resume_decided_gates(
            data, await subscriber._parked_candidate_ids()
        )

    async with session_factory() as session:
        thread = await get_thread(session, "thread-recon-1")
        assert thread is not None
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_gap_reconcile_terminal_verdict_dispatches_without_crash(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """A gate whose proposal is approved attempts its resume gracefully."""
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            _ParkedThreadSeed(
                thread_id="thread-recon-2",
                proposal_ids=["prop_recon"],
                changeset_ids=["cs_recon2"],
                gate_pending="prop_recon",
            ),
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
        await subscriber._resume_decided_gates(
            data, await subscriber._parked_candidate_ids()
        )

    async with session_factory() as session:
        thread = await get_thread(session, "thread-recon-2")
        assert thread is not None
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


def test_gate_resume_verdict_maps_applied_as_approved() -> None:
    from ...thread.enums import VERDICT_APPROVED, VERDICT_REJECTED

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
    from ...thread.enums import (
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
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """The reconcile keys on the CURRENT gate proposal, never a stale earlier one.

    A run accumulates its authoring ids across gates: at the ADR gate its
    authoring_proposal_ids still lists the (applied) research proposal. Correlating
    by any accumulated id would resume the ADR gate on the research verdict and
    complete the run with the ADR unreviewed. The reconcile instead reads
    ``gate_pending_proposal_id`` - the ONE proposal the run is awaiting - so it
    resolves to the ADR proposal, not the stale research one.
    """
    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
        await _seed_parked_thread(
            session_factory,
            checkpointer,
            _ParkedThreadSeed(
                thread_id="thread-adr-gate",
                proposal_ids=["proposal:research", "proposal:adr"],
                changeset_ids=["cs:research", "cs:adr"],
                gate_pending="proposal:adr",
            ),
        )
        subscriber = _make_subscriber(session_factory, checkpointer, worker_client)
        pending = await subscriber._thread_pending_gate_proposal("thread-adr-gate")
        assert pending == "proposal:adr"


@pytest.mark.asyncio
async def test_reconcile_parked_runs_noops_when_none_parked_and_throttles(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """The steady-state parked-run reconcile is cheap and throttled.

    The AUTO submit-time race recovery runs on every idle cycle, so it must no-op
    when nothing is parked (returning BEFORE contacting the engine - an unreachable
    endpoint would raise if it tried to fetch a snapshot) and must not re-run within
    the throttle window.
    """
    from ...authoring import EngineEndpoint

    async with httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client:
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
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """Gate-precision: a late verdict for an EARLIER gate is not applied.

    The run's checkpoint has advanced to the ADR gate (gate_pending =
    ``proposal:adr``) but its research pause row may not yet be superseded. A late
    research request_changes verdict, matched only by that research proposal, must
    NOT resume the run - its current gate is not the one the verdict answers, so
    applying it would consume the ADR gate's interrupt with a stale verdict and
    wedge the run at ``next_nodes=[]``. No dispatch occurs and the run stays parked.
    """
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="superseded",
            proposal_ids=["proposal:research", "proposal:adr"],
            changeset_ids=["cs:research", "cs:adr"],
            gate_pending="proposal:adr",
        ),
    )
    async with served_worker(checkpointer, token=_TEST_INTERNAL_TOKEN) as worker:
        subscriber = _make_subscriber(session_factory, checkpointer, worker.client)
        await subscriber._resume_with_verdict(
            "superseded", "request_changes", None, {"proposal:research"}
        )
        assert len(worker.app.state.dispatch_ids) == 0
    async with session_factory() as session:
        thread = await get_thread(session, "superseded")
        assert thread is not None
        assert thread.status == ThreadStatus.INPUT_REQUIRED.value


@pytest.mark.asyncio
async def test_concurrent_verdict_resumes_elect_one_stable_dispatch(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """Real concurrent sessions elect one dispatcher for the same gate verdict.

    Two triggers (e.g. the SSE per-event path and the reconcile sweep) can fire for
    one gate's verdict. Their independent database sessions race through the shared
    journal reservation and lease primitive. Exactly one dispatches, and its HTTP
    dispatch id is the stable identity persisted on the elected journal row.
    """
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="dedup",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
            team_preset=DEFAULT_TEAM_PRESET,
        ),
    )
    async with served_worker(
        checkpointer, token=_TEST_INTERNAL_TOKEN, receipt_threads=("dedup",)
    ) as worker:
        first = _make_subscriber(session_factory, checkpointer, worker.client)
        second = _make_subscriber(session_factory, checkpointer, worker.client)
        await asyncio.gather(
            first._resume_with_verdict(
                "dedup", "request_changes", None, {"proposal:research"}
            ),
            second._resume_with_verdict(
                "dedup", "request_changes", None, {"proposal:research"}
            ),
        )
        assert len(worker.app.state.dispatch_ids) == 1
    async with session_factory() as session:
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id="dedup",
            idempotency_key=authoring_verdict_action_key("proposal:research"),
        )
        assert action is not None
        assert action.dispatch_id in worker.app.state.dispatch_ids


@pytest.mark.asyncio
async def test_competing_verdict_payloads_share_request_key_and_dispatch_one(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: AsyncSqliteSaver
) -> None:
    """One gate request cannot be rebound to a competing verdict payload."""
    await _seed_parked_thread(
        session_factory,
        checkpointer,
        _ParkedThreadSeed(
            thread_id="competing-verdicts",
            proposal_ids=["proposal:research"],
            changeset_ids=["cs:research"],
            gate_pending="proposal:research",
            team_preset=DEFAULT_TEAM_PRESET,
        ),
    )
    async with served_worker(
        checkpointer,
        token=_TEST_INTERNAL_TOKEN,
        receipt_threads=("competing-verdicts",),
    ) as worker:
        approved = _make_subscriber(session_factory, checkpointer, worker.client)
        rejected = _make_subscriber(session_factory, checkpointer, worker.client)
        await asyncio.gather(
            approved._resume_with_verdict(
                "competing-verdicts", "approved", "ship", {"proposal:research"}
            ),
            rejected._resume_with_verdict(
                "competing-verdicts", "rejected", "revise", {"proposal:research"}
            ),
        )
        assert len(worker.app.state.dispatch_ids) == 1
    async with session_factory() as session:
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id="competing-verdicts",
            idempotency_key=authoring_verdict_action_key("proposal:research"),
        )
        assert action is not None
        assert action.request_id == "proposal:research"
        accepted_input = json.loads(action.payload_json or "null")
        assert accepted_input["schema_version"] == "accepted-action-input-v2"
        # The verdict names the gate it answers, so a resume delivered to a
        # run that has since re-parked is recognisable there.
        assert accepted_input["intent"] in (
            {
                "verdict": "approved",
                "notes": "ship",
                "request_id": "proposal:research",
            },
            {
                "verdict": "rejected",
                "notes": "revise",
                "request_id": "proposal:research",
            },
        )


# Two settlement tests were dropped when the deterministic-scenarios branch
# merged. They asserted that resuming an answered document gate marks its
# permission row APPLIED and clears approval state at terminal - the settlement
# this module used to perform inline. That inline settlement was deliberately
# replaced here by receipt-driven settlement in the worker-event handler, and
# the dropped tests drove a verdict plus a terminal event with no receipt, so
# under the current design the row is still pending when terminal expires it.
# Whether a resolved gate should settle WITHOUT a receipt is a real open
# question, recorded rather than answered by re-asserting the replaced contract.
