"""Live SSE-conformance proof for the verdict subscriber (P03.S08).

No mocks: exercises the real ``AuthoringClient`` lifecycle stream against a live
dashboard engine on loopback, resolved through the same discovery contract the
subscriber uses in production (``resolve_engine``). ``service``-marked and
excluded from the default profile; when no engine is reachable it skips with a
runbook pointer (an infrastructure gate, not a masked failure). Point
``VAULTSPEC_ENGINE_SERVICE_JSON`` at the engine's discovery file for a
``--no-seat`` workspace-local serve.

What this proves live: real durable-outbox lifecycle events, replayed over
``GET /authoring/v1/events``, decode through the subscriber's SSE parser into
``LifecycleEvent`` frames whose ``seq`` / ``event_kind`` / ``aggregate_id``
match the engine wire shape and whose correlation ids are extractable - so a
parked run producing a matched id would be found and a non-verdict event is
correctly ignored.

Honest scope boundary (verified live 2026-07-14, recorded in the S08 Step
Record): against the engine build under test, only ``session.created`` reaches
the ``/events`` outbox - creating and submitting a proposal advanced the outbox
by a single ``session.created`` event and emitted no ``proposal.*`` /
``approval.*`` frames. The reviewer-verdict events the subscriber resumes on
(``approval.resolved`` / ``proposal.rejected``) are therefore not observable
here, so the end-to-end verdict-to-resume hop is NOT proven live. That gap is
engine-side emission, independent of the subscriber, whose verdict decoding and
correlation are proven over real infra in the unit and integration suites.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vaultspec_a2a.authoring import (
    AuthoringClient,
    AuthoringResponse,
    AuthoringSession,
    LifecycleEvent,
    mint_actor_token,
    resolve_engine,
    verdict_from_event,
)


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
