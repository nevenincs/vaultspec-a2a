"""Live verdict-round-trip proof for the subscriber (P03.S08, HIGH-2 addendum).

No mocks: exercises the real ``AuthoringClient`` lifecycle stream against a live
dashboard engine on loopback, resolved through the same discovery contract the
subscriber uses in production (``resolve_engine``). ``service``-marked and
excluded from the default profile; when no engine is reachable it skips with a
runbook pointer (an infrastructure gate, not a masked failure). Point
``VAULTSPEC_ENGINE_SERVICE_JSON`` at the engine's discovery file for a
``--no-seat`` workspace-local serve.

What this proves live against the review-outbox engine build
(dashboard ``a7ad6f3``, verified 2026-07-15): a real proposal's full review
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
from typing import Any

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

from vaultspec_a2a.authoring import (
    AuthoringClient,
    AuthoringResponse,
    AuthoringSession,
    LifecycleEvent,
    mint_actor_token,
    resolve_engine,
    verdict_from_event,
)
from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.verdict_subscriber import VerdictSubscriber
from vaultspec_a2a.control.worker_management import LazyWorkerSpawner
from vaultspec_a2a.database import create_thread, update_thread_status
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.thread.enums import ThreadStatus


@pytest.fixture(scope="module")
def engine() -> tuple[str, str]:
    endpoint = resolve_engine(liveness_timeout=3.0)
    if endpoint is None:
        pytest.skip(
            "no reachable authoring engine; start `vaultspec serve` per the "
            "runbook or set VAULTSPEC_ENGINE_SERVICE_JSON"
        )
    return endpoint.base_url, endpoint.bearer_token


@pytest_asyncio.fixture
async def client(engine: tuple[str, str]):
    base_url, bearer = engine
    async with AuthoringClient(base_url, bearer) as authoring_client:
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

        # (b) each decision frame carries the pinned verdict + notes, rides the
        #     a7ad6f3 event kind, and correlates to the run seeded for that
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
