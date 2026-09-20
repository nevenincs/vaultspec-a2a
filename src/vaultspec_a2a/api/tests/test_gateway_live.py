"""Live gateway coverage for the six-member whitelist and separate SSE stream.

Replaces the deleted UI contract coverage: the browser SPA was the only
end-to-end exerciser of the gateway edge, and it is gone. These tests drive the
real app over a REAL TCP socket (a uvicorn server on an ephemeral port), not
``ASGITransport`` — the earlier ASGI-transport approach deadlocked a mid-stream
SSE emit/read because it buffers the whole response before returning, so a
producer and a streaming consumer could never run concurrently. A real socket
streams incrementally, so the SSE test can emit an event mid-stream and read it
back on the same loop.

No mocks: the app carries the real EventAggregator, the real AsyncSqliteSaver
checkpointer, a real SQLite thread store, and the conftest in-process worker
that records dispatches over real HTTP.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

import httpx
import pytest
import uvicorn

from ...control.accepted_input import freeze_accepted_input
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.execution_authority import resolve_execution_authority
from ...control.tests._catalog_authority import current_execution_metadata
from ...database import create_control_action, create_thread, list_threads
from ...ipc.schemas import DispatchRequest
from ...streaming.aggregator import EventAggregator
from ...team.team_config import load_team_config
from ...testing.tests._support.catalog_selection import in_process_selection
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ..routes.gateway import admission_gate
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping

    from fastapi import FastAPI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from ...control.drain import DrainGate
    from ...thread.action_receipts import GraphActionReceipt
    from .conftest import _InProcessWorker

type SessionFactory = async_sessionmaker[AsyncSession]
type JsonValue = bool | int | float | str | list[JsonValue] | JsonObject | None
type JsonObject = dict[str, JsonValue]


@runtime_checkable
class _CheckedOutPool(Protocol):
    """The SQLAlchemy pool operation needed to prove the real insert race."""

    def checkedout(self) -> int: ...


@runtime_checkable
class _SqlTraceConnection(Protocol):
    """The real aiosqlite tracing operation used by the coherence regression."""

    async def set_trace_callback(
        self, trace_callback: Callable[[str], object] | None
    ) -> None: ...


async def _set_sql_trace_callback(
    connection: object, trace_callback: Callable[[str], object] | None
) -> None:
    """Install a trace on the concrete SQLite connection after structural proof."""
    if not isinstance(connection, _SqlTraceConnection):
        raise AssertionError("AsyncSqliteSaver did not expose SQLite trace support")
    await _apply_sql_trace_callback(connection, trace_callback)


async def _apply_sql_trace_callback(
    connection: _SqlTraceConnection, trace_callback: Callable[[str], object] | None
) -> None:
    """Keep the untyped third-party connection behind the tested protocol seam."""
    await connection.set_trace_callback(trace_callback)


_PRESET = "mock-success-single"


async def _seed_live_thread(
    session_factory: SessionFactory, *, title: str
) -> tuple[str, GraphActionReceipt]:
    """Create a live run with the accepted action startup recovery requires."""
    workspace = Path.cwd()
    metadata = current_execution_metadata(workspace)
    authority = make_test_write_authority()
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=authority,
            status=ThreadStatus.RUNNING,
            team_preset=_PRESET,
            title=title,
            metadata=metadata,
        )
        dispatch = DispatchRequest(
            action="ingest",
            thread_id=thread.id,
            content="live stream fixture",
            workspace_root=str(workspace),
            recursion_limit=25,
            team_preset=_PRESET,
            graph_definition=freeze_graph_definition(
                load_team_config(_PRESET, workspace_root=workspace),
                workspace_root=workspace,
            ),
            model_assignment=resolve_execution_authority(metadata).model_assignment,
        )
        await create_control_action(
            session,
            thread_id=thread.id,
            action_type=authority.action_type,
            idempotency_key=f"thread-create:{thread.id}",
            dispatch_id=authority.action_receipt_id,
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            payload=freeze_accepted_input(
                dispatch, intent={"content": "live stream fixture"}
            ),
        )
        receipt = await prepare_graph_action_receipt(
            session, thread_id=thread.id, dispatch_id=authority.action_receipt_id
        )
        assert receipt is not None
        await session.commit()
        return thread.id, receipt


async def _in_process_catalog_selection(
    client: httpx.AsyncClient,
) -> tuple[JsonObject, str]:
    """Read one genuinely served in-process lane as a public selection reference.

    In-process rather than merely selectable: these tests assert on gateway
    verbs - replay, conflict, cancellation - and make no provider claim, so the
    lane that answers must be one that bills nothing. The suite's catalog
    service arms those lanes for exactly this reason.
    """
    workspace_root = str(Path.cwd())
    response = await client.get(
        "/v1/provider-catalog", params={"workspace_root": workspace_root}
    )
    assert response.status_code == 200, response.text
    return in_process_selection(response.json()), workspace_root


async def _run_fields(client: httpx.AsyncClient) -> dict[str, object]:
    """Return the run-start fields an explicit catalog selection now requires.

    Deterministic for a given served catalog, which is what makes it safe in
    this module: several tests here post the SAME body twice to prove a replay
    converges, or vary one field to prove a conflict is detected. A selection
    that differed per call would turn every replay into a conflict and quietly
    invert what those tests assert.
    """
    # Read the catalog on its OWN budget rather than the caller's. Every client
    # in this module is built with a 10s timeout, which exists to assert the
    # gateway answers its verbs promptly; the first catalog read in a process
    # also probes each provider lane and legitimately takes longer than that.
    # Borrowing the caller's budget made a cold probe look like an unresponsive
    # gateway. Subsequent reads are served from the catalog's own cache.
    async with httpx.AsyncClient(base_url=client.base_url, timeout=120.0) as probe:
        selection, workspace_root = await _in_process_catalog_selection(probe)
    return {"selection": selection, "metadata": {"workspace_root": workspace_root}}


async def _seed_permission(
    session_factory: SessionFactory, *, thread_id: str, request_id: str
) -> None:
    """Record a real pending permission request against a real run."""
    from ...database.permission_repository import record_permission_request

    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="bash",
            description="Allow action?",
            allowed_options=[
                {
                    "option_id": "allow_once",
                    "name": "Allow once",
                    "kind": "allow_once",
                }
            ],
            tool_call="bash",
        )
        await session.commit()


@pytest.mark.asyncio(loop_scope="function")
async def test_run_history_is_the_wide_read_that_run_status_deliberately_is_not(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """History carries the record; run-status stays the bounded authority read.

    The two are asserted against each other rather than in isolation, because
    the point of adding history was NOT to widen run-status: an engine
    reconciling authority should not pay for a transcript it never reads. So
    this pins that history carries the transcript and metadata, and that
    run-status still does not.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-01",
                "team_preset": _PRESET,
                "message": "remember this",
                "autonomous": True,
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201
        run_id = start.json()["run_id"]

        history = await client.get(f"/v1/runs/{run_id}/history")
        assert history.status_code == 200
        hbody = history.json()
        assert hbody["api_version"] == "v1"
        assert hbody["run_id"] == run_id
        # The wide read: the state snapshot is embedded whole.
        assert "messages" in hbody["state"]
        assert "agents" in hbody["state"]
        # Present as a field whether or not this run carried metadata; the wide
        # read reports its absence rather than omitting the key.
        assert "metadata" in hbody

        # Run-status is deliberately narrower - it is the recovery snapshot, and
        # widening it was the alternative this verb exists to avoid.
        status = await client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200
        assert "messages" not in status.json()

        missing = await client.get("/v1/runs/no-such-run/history")
        assert missing.status_code == 404


@pytest.mark.asyncio(loop_scope="function")
async def test_archive_and_team_status_are_reachable_on_the_versioned_surface(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Two reads-and-a-transition the transition surface used to hold alone.

    Archiving is not deletion - the run survives, marked historical - so the
    test asserts it is still there afterwards rather than trusting the status
    string. Team status is asserted to carry the operational projection and to
    surface the run as active while it is live.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-02",
                "team_preset": _PRESET,
                "message": "work",
                "autonomous": True,
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201
        run_id = start.json()["run_id"]

        team = await client.get("/v1/team/status")
        assert team.status_code == 200
        tbody = team.json()
        assert tbody["api_version"] == "v1"
        assert isinstance(tbody["agents"], list)
        assert isinstance(tbody["pending_permissions"], list)
        # ``active_runs`` is the WORKER's heartbeat view, not a database read, so
        # it stays empty until a worker reports its live set - asserted as the
        # shape it is rather than as the database answer it is not. Getting this
        # wrong would have written a test that passes only when a worker happens
        # to have checked in.
        assert isinstance(tbody["active_runs"], list)

        # A running run cannot be archived; the refusal is a conflict.
        too_early = await client.post(f"/v1/runs/{run_id}/archive")
        assert too_early.status_code == 409

        await client.post(f"/v1/runs/{run_id}/cancel")
        # Cancellation reaches CANCELLING, not a terminal state, so archiving is
        # still refused - asserted rather than assumed, because a test that
        # archived here would be proving the wrong lifecycle.
        assert (await client.post(f"/v1/runs/{run_id}/archive")).status_code == 409

        missing = await client.post("/v1/runs/no-such-run/archive")
        assert missing.status_code == 404


@pytest.mark.asyncio(loop_scope="function")
async def test_a_follow_up_turn_reaches_the_run_that_run_start_cannot_address(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The versioned surface can now say something further to a live run.

    This is the capability run-start structurally cannot provide, and the test
    proves that rather than asserting it: re-posting to run-start with the same
    run id returns the ORIGINAL run and dispatches nothing new, because a repeat
    identifier there is a replay. The follow-up verb dispatches for real.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "team_preset": _PRESET,
                "message": "first turn",
                "autonomous": True,
                "run_id": "r-followup",
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201
        run_id = start.json()["run_id"]

        # Run-start with the same id is a REPLAY: same run back, no new dispatch.
        worker.dispatches.clear()
        replay = await client.post(
            "/v1/runs",
            json={
                "team_preset": _PRESET,
                "message": "first turn",
                "autonomous": True,
                "run_id": "r-followup",
                **await _run_fields(client),
            },
        )
        assert replay.status_code == 201
        assert replay.json()["run_id"] == run_id
        assert worker.dispatches == [], "a replay must not dispatch a new turn"

        # The follow-up verb is how a second turn actually reaches the run.
        follow = await client.post(
            f"/v1/runs/{run_id}/messages",
            json={"content": "second turn"},
        )
        assert follow.status_code == 202
        body = follow.json()
        assert body["api_version"] == "v1"
        assert body["run_id"] == run_id
        assert body["accepted"] is True
        # Accepted is not applied: the turn is handed on, not completed here.
        assert body["applied"] is False
        assert len(worker.dispatches) == 1
        assert worker.dispatches[-1]["content"] == "second turn"

        # An unknown run is a not-found rather than a silent accept.
        missing = await client.post(
            "/v1/runs/no-such-run/messages", json={"content": "hello"}
        )
        assert missing.status_code == 404


@pytest.mark.asyncio(loop_scope="function")
async def test_the_versioned_verb_answers_a_permission_and_refuses_a_foreign_one(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The versioned surface can now accept the answer to what it asks.

    ``permission_request`` is already an enumerated frame on run-stream, so the
    question is versioned while the answer used to exist only on the transition
    surface. This drives the answer over a real socket and pins three things: it
    works, it is at-most-once, and it is scoped to the run that raised it.

    The scoping case is the one that matters most. A request id names a request,
    not a run, so without the check a caller holding one run's id could answer
    another run's question. The refusal must also leave the request untouched -
    proven by answering it afterwards for real, which would be impossible had
    the refused attempt consumed it.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):

        async def _start(run_id: str, message: str) -> str:
            # Each start needs its OWN stable id: the two runs here are distinct
            # intentions, and reusing one id would turn the second start into a
            # changed-body replay the gateway rightly refuses with a 409.
            resp = await client.post(
                "/v1/runs",
                json={
                    "run_id": run_id,
                    "team_preset": _PRESET,
                    "message": message,
                    "autonomous": True,
                    **await _run_fields(client),
                },
            )
            assert resp.status_code == 201, resp.text
            return resp.json()["run_id"]

        owner = await _start("gwlive-05", "owns the permission")
        stranger = await _start("gwlive-06", "owns nothing")
        request_id = f"{owner}:req-live"
        await _seed_permission(session_factory, thread_id=owner, request_id=request_id)

        # Scoped: the stranger cannot answer the owner's question, and the
        # refusal is a not-found rather than a leak that the id exists.
        foreign = await client.post(
            f"/v1/runs/{stranger}/permissions/{request_id}/respond",
            json={"option_id": "allow_once"},
        )
        assert foreign.status_code == 404

        worker.dispatches.clear()
        first = await client.post(
            f"/v1/runs/{owner}/permissions/{request_id}/respond",
            json={"option_id": "allow_once"},
        )
        assert first.status_code == 200
        body = first.json()
        assert body["api_version"] == "v1"
        assert body["run_id"] == owner
        assert body["request_id"] == request_id
        assert body["accepted"] is True
        # The refused attempt consumed nothing: this answer was still taken.
        # ``applied`` is false because this run is not parked awaiting the
        # decision - the answer is recorded and a resume dispatched, but there
        # was no paused execution for it to release. Asserted as observed rather
        # than as expected: the load-bearing claim here is that the answer was
        # accepted and dispatched exactly once, not that it unblocked anything.
        assert body["action_status"] == "accepted_not_applied"
        assert body["idempotency_key"]
        assert len(worker.dispatches) == 1

        # At-most-once: the same answer again reports the stored outcome and
        # does not resume the run a second time.
        resumes_after_first = len(worker.dispatches)
        second = await client.post(
            f"/v1/runs/{owner}/permissions/{request_id}/respond",
            json={"option_id": "allow_once"},
        )
        assert second.status_code == 200
        # Not merely "a success": the SAME stored outcome, down to the derived
        # idempotency key. A second answer that re-derived anything differs here.
        assert second.json() == body
        assert len(worker.dispatches) == resumes_after_first

        # An unknown request on a real run is not found rather than a 500.
        unknown = await client.post(
            f"/v1/runs/{owner}/permissions/{owner}:nope/respond",
            json={"option_id": "allow_once"},
        )
        assert unknown.status_code == 404


@pytest.mark.asyncio(loop_scope="function")
async def test_legacy_lease_only_metadata_remains_status_visible(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """run-status carries a valid legacy lease and rejects an invalid one."""
    from ...database.thread_repository import create_thread
    from ...thread.enums import ThreadStatus

    valid_metadata: JsonObject = {"run_lease": {"lease_id": "lease-legacy123"}}
    invalid_metadata: JsonObject = {"run_lease": {"lease_id": "not/addressable"}}
    async with session_factory() as session:
        valid = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            status=ThreadStatus.RUNNING,
            title="legacy valid lease",
            metadata=json.dumps(valid_metadata),
        )
        invalid = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            status=ThreadStatus.RUNNING,
            title="legacy invalid lease",
            metadata=json.dumps(invalid_metadata),
        )
        await session.commit()

    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        valid_status = await client.get(f"/v1/runs/{valid.id}")
        invalid_status = await client.get(f"/v1/runs/{invalid.id}")

    assert valid_status.status_code == 200, valid_status.text
    assert valid_status.json()["lease_id"] == "lease-legacy123"
    assert invalid_status.status_code == 200, invalid_status.text
    assert invalid_status.json()["lease_id"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_run_status_projects_one_stored_checkpoint_tuple(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The TCP gateway projects one real stored tuple without a second latest read."""
    from langgraph.checkpoint.base import empty_checkpoint

    from ...database.thread_repository import create_thread
    from ...thread.enums import ThreadStatus

    thread_id = "coherent-status-capture"
    metadata: JsonObject = {"run_lease": {"lease_id": "lease-coherent"}}
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=ThreadStatus.RUNNING,
            title="coherent tuple",
            team_preset=_PRESET,
            metadata=json.dumps(metadata),
        )
        await session.commit()

    checkpoint = empty_checkpoint()
    checkpoint["id"] = "checkpoint-coherent"
    checkpoint["channel_values"].update(
        {
            "authoring_proposal_ids": ["proposal-coherent"],
            "authoring_changeset_ids": ["changeset-coherent"],
            "active_feature": "feature-coherent",
            "authoring_session_id": "session-coherent",
        }
    )
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )

    statements: list[str] = []
    connection = checkpointer.conn
    await _set_sql_trace_callback(connection, statements.append)
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    try:
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        ):
            response = await client.get(f"/v1/runs/{thread_id}")
    finally:
        await _set_sql_trace_callback(connection, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkpoint_id"] == "checkpoint-coherent"
    assert body["proposal_ids"] == ["proposal-coherent"]
    assert body["changeset_ids"] == ["changeset-coherent"]
    assert body["feature_tag"] == "feature-coherent"
    assert body["authoring_session_id"] == "session-coherent"
    assert body["topology"]["team_preset"] == _PRESET
    assert body["lease_id"] == "lease-coherent"
    latest_tuple_reads = [
        statement
        for statement in statements
        if "ORDER BY CHECKPOINT_ID DESC LIMIT 1" in " ".join(statement.upper().split())
    ]
    assert len(latest_tuple_reads) == 1, latest_tuple_reads


@asynccontextmanager
async def _live_server(app: FastAPI) -> AsyncGenerator[str]:
    """Serve *app* on an ephemeral port and yield its base URL."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started and server.servers:
                break
            await asyncio.sleep(0.01)
        assert server.started and server.servers, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5.0)


async def _wait_until(
    predicate: Callable[[], bool], *, what: str, timeout: float = 10.0
) -> None:
    """Poll *predicate* until true, failing the test rather than racing on."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


async def _run_same_id_insert_race(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    gate: DrainGate,
    checked_out: Callable[[], int],
    run_id: str,
    payload: Mapping[str, object],
) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
    barrier = await engine.connect()
    baseline = checked_out()
    await barrier.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        first = asyncio.create_task(client.post("/v1/runs", json=payload))
        await _wait_until(
            lambda: gate.is_active(run_id),
            what="the first modern request to pass its read",
        )
        second = asyncio.create_task(client.post("/v1/runs", json=payload))
        await _wait_until(
            lambda: checked_out() >= baseline + 2,
            what="the second modern request to reach the store",
        )
        await asyncio.sleep(0.25)
    finally:
        await barrier.exec_driver_sql("ROLLBACK")
        await barrier.close()
    first_response, second_response = await asyncio.gather(first, second)
    replay = await client.post("/v1/runs", json=payload)
    return first_response, second_response, replay


async def _exercise_five_verbs(
    client: httpx.AsyncClient, worker: _InProcessWorker
) -> None:
    """Exercise the five versioned gateway verbs over one live socket."""
    presets = await client.get("/v1/presets")
    assert presets.status_code == 200
    pbody = presets.json()
    assert pbody["api_version"] == "v1"
    assert any(p["id"] == _PRESET for p in pbody["presets"])

    service = await client.get("/v1/service")
    assert service.status_code == 200
    sbody = service.json()
    assert sbody["api_version"] == "v1"
    # Status is probe-derived, not hardcoded: the in-process worker /health,
    # real DB, and real checkpointer all answer, so the service is ready.
    assert sbody["status"] == "ready"
    assert isinstance(sbody["ready"], bool)

    start = await client.post(
        "/v1/runs",
        json={
            "run_id": "gwlive-06",
            "team_preset": _PRESET,
            "message": "build it",
            "autonomous": True,
            "actor_tokens": {
                "tokens": {"coder": "tok-coder"},
                "engine_bearer": "bearer",
            },
            **await _run_fields(client),
        },
    )
    assert start.status_code == 201
    stbody = start.json()
    assert stbody["api_version"] == "v1"
    run_id = stbody["run_id"]
    assert run_id
    assert worker.dispatches, "run-start must dispatch to the worker"
    assert worker.dispatches[-1]["actor_tokens"]["tokens"]["coder"] == "tok-coder"

    status = await client.get(f"/v1/runs/{run_id}")
    assert status.status_code == 200
    rbody = status.json()
    assert rbody["api_version"] == "v1"
    assert rbody["run_id"] == run_id
    assert rbody["topology"]["team_preset"] == _PRESET
    assert "roles" in rbody
    assert isinstance(rbody["proposal_ids"], list)
    # Semantic phase projection: a dispatched coder run is a generic
    # "running" (no fabricated authoring precision for a non-research_adr
    # preset), and the target-feature / authoring-session fields are present.
    assert rbody["semantic_phase"] == "running"
    assert "feature_tag" in rbody
    assert "authoring_session_id" in rbody

    missing = await client.get("/v1/runs/does-not-exist")
    assert missing.status_code == 404

    first = await client.post(f"/v1/runs/{run_id}/cancel")
    assert first.status_code == 200
    assert first.json()["api_version"] == "v1"
    second = await client.post(f"/v1/runs/{run_id}/cancel")
    assert second.status_code == 200


async def _run_nickname_insert_race(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    gate: DrainGate,
    checked_out: Callable[[], int],
    selection: Mapping[str, object],
    workspace_root: str,
) -> tuple[httpx.Response, httpx.Response]:
    """Race two distinct ids through one durable nickname collision."""
    nickname = "shared-modern-race"
    left_id = "rid-modern-nickname-left"
    right_id = "rid-modern-nickname-right"
    nickname_base: dict[str, object] = {
        "team_preset": _PRESET,
        "message": "nickname collision",
        "selection": selection,
        "metadata": {
            "workspace_root": workspace_root,
            "nickname": nickname,
        },
    }
    await _wait_until(
        lambda: checked_out() == 0,
        what="the same-id race connections to return to the pool",
    )
    barrier = await engine.connect()
    baseline = checked_out()
    await barrier.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        # `nickname_base` already carries the selection AND the metadata naming
        # the shared nickname; adding `_run_fields` would dissolve the collision.
        left = asyncio.create_task(
            client.post(
                "/v1/runs",
                json={**nickname_base, "run_id": left_id},
            )
        )
        await _wait_until(
            lambda: gate.is_active(left_id),
            what="the first nickname request to pass its read",
        )
        right = asyncio.create_task(
            client.post(
                "/v1/runs",
                json={**nickname_base, "run_id": right_id},
            )
        )
        await _wait_until(
            lambda: checked_out() >= baseline + 2,
            what="the second nickname request to reach the store",
        )
        await asyncio.sleep(0.25)
    finally:
        await barrier.exec_driver_sql("ROLLBACK")
        await barrier.close()
    return await asyncio.gather(left, right)


def _assert_modern_race_results(
    responses: tuple[httpx.Response, httpx.Response, httpx.Response],
    nickname_responses: tuple[httpx.Response, httpx.Response],
    *,
    caplog: pytest.LogCaptureFixture,
    worker: _InProcessWorker,
    run_id: str,
) -> None:
    """Assert freeze convergence and the inverse nickname collision outcome."""
    assert all(response.status_code == 201 for response in responses), [
        response.text for response in responses
    ]
    assert [
        record
        for record in caplog.records
        if "lost a concurrent insert race" in record.getMessage()
        and run_id in record.getMessage()
    ], "the integrity-error recovery branch did not execute"
    frozen = [response.json()["frozen_assignment"] for response in responses]
    assert all(item is not None for item in frozen)
    assert frozen[0] == frozen[1] == frozen[2]
    assert frozen[0]["schema_version"] == 1
    assert frozen[0]["digest"]
    assert len([d for d in worker.dispatches if d.get("thread_id") == run_id]) == 1
    assert sorted(response.status_code for response in nickname_responses) == [201, 409]
    nickname_conflict = next(
        response for response in nickname_responses if response.status_code == 409
    )
    assert "nickname already exists" in nickname_conflict.json()["detail"]
    nickname_dispatches = [
        dispatch
        for dispatch in worker.dispatches
        if dispatch.get("thread_id")
        in {"rid-modern-nickname-left", "rid-modern-nickname-right"}
    ]
    assert len(nickname_dispatches) == 1


async def _run_modern_selection_races(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    gate: DrainGate,
    checked_out: Callable[[], int],
    run_id: str,
    selection: Mapping[str, object],
    workspace_root: str,
) -> tuple[
    tuple[httpx.Response, httpx.Response, httpx.Response],
    tuple[httpx.Response, httpx.Response],
]:
    """Run the same-id and inverse nickname races for one catalog selection."""
    payload = {
        "team_preset": _PRESET,
        "message": "same durable intention",
        "run_id": run_id,
        "selection": selection,
        "metadata": {"workspace_root": workspace_root},
    }
    first_response, second_response, replay = await _run_same_id_insert_race(
        client,
        engine,
        gate,
        checked_out,
        run_id,
        payload,
    )
    nickname_responses = await _run_nickname_insert_race(
        client,
        engine,
        gate,
        checked_out,
        selection,
        workspace_root,
    )
    return (first_response, second_response, replay), nickname_responses


async def _run_different_body_race(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    gate: DrainGate,
    checked_out: Callable[[], int],
    run_id: str,
    first_body: Mapping[str, object],
    second_body: Mapping[str, object],
) -> tuple[httpx.Response, httpx.Response, httpx.Response, Mapping[str, object]]:
    """Race two bodies for one id, then replay the winner's body."""
    barrier = await engine.connect()
    race_fields = await _run_fields(client)
    baseline = checked_out()
    await barrier.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        first = asyncio.create_task(
            client.post(
                "/v1/runs",
                json={
                    **first_body,
                    **race_fields,
                },
            )
        )
        # Admission happens after the check-then-act read and before the insert,
        # so an active run id proves the first request read an absent run.
        await _wait_until(
            lambda: gate.is_active(run_id),
            what="the first request to pass its read",
        )
        second = asyncio.create_task(
            client.post(
                "/v1/runs",
                json={
                    **second_body,
                    **race_fields,
                },
            )
        )
        # A second leased connection proves the second request is issuing DB
        # work of its own while the barrier bars every insert.
        await _wait_until(
            lambda: checked_out() >= baseline + 2,
            what="the second request to reach the store",
        )
        await asyncio.sleep(0.25)
    finally:
        await barrier.exec_driver_sql("ROLLBACK")
        await barrier.close()
    first_response, second_response = await asyncio.gather(first, second)
    if first_response.status_code == 201:
        winner, loser = first_response, second_response
        winning_body = first_body
    else:
        winner, loser = second_response, first_response
        winning_body = second_body
    # The winner's own request still replays after the colliding body is refused.
    replay = await client.post("/v1/runs", json={**winning_body, **race_fields})
    return winner, loser, replay, winning_body


async def _assert_different_body_race(
    race: tuple[
        httpx.Response,
        httpx.Response,
        httpx.Response,
        Mapping[str, object],
    ],
    *,
    session_factory: SessionFactory,
    worker: _InProcessWorker,
    gate: DrainGate,
    caplog: pytest.LogCaptureFixture,
    run_id: str,
) -> None:
    """Assert the loser is refused and only the winner is durable and dispatched."""
    winner, loser, replay, winning_body = race
    assert sorted(r.status_code for r in (winner, loser)) == [201, 409], [
        winner.text,
        loser.text,
    ]
    assert [
        record
        for record in caplog.records
        if "lost a concurrent insert race" in record.getMessage()
        and run_id in record.getMessage()
    ], "the integrity-error branch did not execute"
    assert winner.json()["run_id"] == run_id
    assert "different request body" in loser.json()["detail"]
    assert replay.status_code == 201, replay.text
    assert replay.json()["run_id"] == run_id

    async with session_factory() as verify:
        _rows, total = await list_threads(verify)
    assert total == 1
    raced = [d for d in worker.dispatches if d.get("thread_id") == run_id]
    assert len(raced) == 1
    assert raced[0]["content"] == winning_body["message"]
    assert gate.is_active(run_id)


@pytest.mark.asyncio(loop_scope="function")
async def test_five_verbs_over_live_socket(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        await _exercise_five_verbs(client, worker)


@pytest.mark.asyncio(loop_scope="function")
async def test_service_state_degrades_when_circuit_breaker_opens(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A real dependency failure (open circuit) degrades service-state.

    Evidence battery: an open worker circuit breaker is a genuine dependency
    failure. service-state must report it truthfully - not ready, status degraded,
    the failure named in degraded_reasons - rather than a hardcoded ok.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    # Trip the real circuit breaker the gateway reads, then probe service-state.
    app.state.circuit_breaker.force_open()

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get("/v1/service")
        assert resp.status_code == 200
        body = resp.json()
        assert body["alive"] is True  # process still answers
        assert body["can_accept_run"] is False  # but cannot accept a run
        assert body["status"] == "degraded"
        assert body["circuit_breaker"] == "open"
        assert any("circuit_breaker" in reason for reason in body["degraded_reasons"])


@pytest.mark.asyncio(loop_scope="function")
async def test_service_state_degrades_when_recovery_owner_fails(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    app.state.direct_control_recovery_error = "recovery_pass_failed"

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get("/v1/service")
        assert resp.status_code == 200
        body = resp.json()

    assert body["alive"] is True
    assert body["can_accept_run"] is False
    assert body["status"] == "degraded"
    assert body["readiness"]["gateway_readiness"] == "ready"
    assert body["readiness"]["run_admission"] == "blocked"
    assert any("recovery_owner" in reason for reason in body["degraded_reasons"])
    assert "recovery owner failed" in body["readiness"]["reasons"]


@pytest.mark.asyncio(loop_scope="function")
async def test_run_status_carries_reconnect_cursor(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """run-status carries the TRUE monotonic last_sequence reconnect cursor.

    Evidence battery, SSE reconnect with non-authoritative semantics: durable
    reconnect reconciliation comes from run-status (last_sequence), not from the
    droppable SSE progress stream.

    F66: this test previously asserted only the field's TYPE
    (``isinstance(..., int)``), which a permanently-zero cursor also satisfies
    -- so it passed against the F19 defect (last_sequence always 0 after a run
    settles) for as long as that defect existed, naming a contract it did not
    actually check. Widened to advance the aggregator's real counter, settle
    the run through the SAME terminal handler production dispatch uses, and
    assert the value the LIVE HTTP read recovers is the one advanced before
    settle -- the read that actually exercises the reconnect-cursor contract,
    since a reconnecting client only ever reads run-status after a run has
    already ended.
    """
    from langgraph.checkpoint.base import empty_checkpoint

    from ...control.event_handlers import _handle_terminal_event
    from ...thread.action_receipts import GraphCompletionReceipt

    run_id, receipt = await _seed_live_thread(session_factory, title="cursor")
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"cp-{run_id}"
    checkpoint["channel_values"] = {
        "active_graph_action_receipt": receipt.model_dump(mode="json"),
        "graph_action_receipts": {receipt.dispatch_id: receipt.model_dump(mode="json")},
        "graph_completion_receipts": {
            receipt.dispatch_id: GraphCompletionReceipt(
                schema_version="graph-completion-v1",
                action=receipt,
                outcome="completed",
            ).model_dump(mode="json")
        },
    }
    checkpoint["channel_versions"] = {
        "active_graph_action_receipt": 1,
        "graph_action_receipts": 1,
        "graph_completion_receipts": 1,
    }
    await checkpointer.aput(
        {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        checkpoint["channel_versions"],
    )

    app, agg, _worker, _cp = make_app(session_factory, checkpointer)
    for _ in range(5):
        agg.advance_sequence(run_id)

    await _handle_terminal_event(
        run_id,
        {"event_type": "thread_terminal", "status": "completed"},
        aggregator=agg,
        session_factory=session_factory,
        checkpointer=checkpointer,
    )
    # The prune genuinely ran: the live in-memory counter is gone, matching
    # what a reconnecting client's HTTP read below has to contend with.
    assert agg.get_sequence(run_id) == 0

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get(f"/v1/runs/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "last_sequence" in body
        assert isinstance(body["last_sequence"], int)
        assert body["last_sequence"] == 5
        assert body["last_sequence"] != 0


@pytest.mark.asyncio(loop_scope="function")
async def test_service_state_is_probe_backed_and_distinguishes_readiness(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """service-state reports truthful probe-derived readiness fields."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get("/v1/service")
        assert resp.status_code == 200
        body = resp.json()

        # Versions, identity, capacity.
        assert body["service_version"]
        assert isinstance(body["gateway_pid"], int)
        assert body["active_run_capacity"] is not None

        # Alive vs can-accept-run are distinct fields; both true in this app.
        assert body["alive"] is True
        assert body["can_accept_run"] is True
        assert body["status"] == "ready"

        # Real probe results are surfaced.
        assert body["database_ready"] is True
        assert body["checkpoint_ready"] is True
        assert body["worker_ready"] is True
        assert body["degraded_reasons"] == []

        # Authoring-backend reachability is a non-blocking tri-state derived from
        # discovery-file freshness (True fresh / False stale / None not wired);
        # its exact value depends on the host's engine discovery file.
        assert body["authoring_backend_reachable"] in (None, True, False)


@pytest.mark.asyncio(loop_scope="function")
async def test_presets_list_is_truthful_and_resilient(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    tmp_path: Path,
) -> None:
    """presets-list marks loadable/unloadable and survives one bad preset."""
    teams_dir = tmp_path / ".vaultspec" / "teams"
    teams_dir.mkdir(parents=True)
    # A malformed workspace preset: valid TOML, invalid schema (no [team]).
    (teams_dir / "broken-preset.toml").write_text(
        "not_a_team = true\n", encoding="utf-8"
    )

    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get("/v1/presets", params={"workspace_root": str(tmp_path)})
        assert resp.status_code == 200
        body = resp.json()
        by_id = {p["id"]: p for p in body["presets"]}

        # The malformed workspace preset is listed as unloadable, not omitted.
        assert "broken-preset" in by_id
        assert by_id["broken-preset"]["loadable"] is False
        broken_reason = by_id["broken-preset"]["unavailable_reason"]
        assert broken_reason
        # The reason is path-free: the workspace/preset filesystem path must not
        # leak into the served discovery record (review LOW fold-in).
        assert str(tmp_path) not in broken_reason
        assert ".vaultspec" not in broken_reason and ".toml" not in broken_reason

        # A bundled coder preset loads and is marked mock.
        assert by_id[_PRESET]["loadable"] is True
        assert by_id[_PRESET]["is_mock"] is True
        assert by_id[_PRESET]["authoring_capability"] == "coding"

        # The document-authoring preset reports its capability and roles.
        authoring = by_id["vaultspec-adr-research"]
        assert authoring["loadable"] is True
        assert authoring["is_mock"] is False
        assert authoring["authoring_capability"] == "document_authoring"
        assert "vaultspec-researcher" in authoring["required_roles"]

        assert authoring["origin"] == "bundled"
        assert authoring["supported_capabilities"] == [
            "research_document",
            "architecture_decision",
            "plan_document",
        ]
        assert "profiles" not in authoring
        assert "default_profile_id" not in authoring

        # No credential VALUE appears anywhere in the served discovery record.
        # Safe readiness reasons and profile descriptions legitimately name a
        # credential TYPE ("Z.ai auth token", "OAuth") - the system disclosing what
        # is absent, not a leak - so the innocent type words are NOT banned. The
        # strong, value-based check asserts the real configured secret values are
        # absent, plus canary markers that would only surface in a raw env/
        # credential dump.
        from ...control.config import settings

        raw = resp.text
        for secret_value in (
            settings.zai_auth_token,
            settings.claude_code_oauth_token,
            settings.openai_api_key,
            settings.zhipu_api_key,
        ):
            if secret_value and secret_value.strip():
                assert secret_value not in raw
        lowered = raw.lower()
        for canary in ("api_key", "secret", "password", "bearer "):
            assert canary not in lowered


@pytest.mark.asyncio(loop_scope="function")
async def test_presets_list_refuses_workspace_model_policy(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> None:
    teams_dir = tmp_path / ".vaultspec" / "teams"
    teams_dir.mkdir(parents=True)
    (teams_dir / "ws-team.toml").write_text(
        '[team]\nid = "ws-team"\ndisplay_name = "WS Team"\n'
        '[team.topology]\ntype = "pipeline"\norder = ["vaultspec-researcher"]\n'
        '[[team.workers]]\nagent_id = "vaultspec-researcher"\n'
        '[team.profiles.fast]\ndisplay_name = "Fast"\n',
        encoding="utf-8",
    )
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with _live_server(app) as base, httpx.AsyncClient(base_url=base) as client:
        response = await client.get(
            "/v1/presets", params={"workspace_root": str(tmp_path)}
        )
    ws_team = next(p for p in response.json()["presets"] if p["id"] == "ws-team")
    assert ws_team["loadable"] is False
    assert "profiles" not in ws_team


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_threads_feedback_batch_id_to_worker(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The opaque feedback_batch_id threads run-start -> metadata -> worker dispatch.

    Feedback-loop carrier: a2a transports the opaque id only. The
    run-start body carries it, the gateway folds it onto the run metadata, and the
    dispatch the worker receives carries it verbatim - the same path active_feature
    rides. a2a never parses the id; retrieval is the worker's engine read.

    Sited in the shared workspace `_run_fields` resolves against: a selection is
    revalidated against the catalog served FOR ITS WORKSPACE, and pointing the
    run at a fresh temporary directory forces a cold per-workspace catalog build
    inside this request's 10s budget - a slow catalog then reads as a gateway
    failure in a test about feedback-id threading.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-08",
                "team_preset": _PRESET,
                "message": "revise the draft",
                "autonomous": True,
                "feedback_batch_id": "feedback-batch:deadbeefcafe",
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201, start.text
        # The dispatch the worker received carries the opaque id verbatim.
        assert worker.dispatches, "run-start must dispatch to the worker"
        assert (
            worker.dispatches[-1]["feedback_batch_id"] == "feedback-batch:deadbeefcafe"
        )


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_without_feedback_batch_id_dispatches_none(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A run with no feedback batch dispatches a null id (non-feedback run)."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-09",
                "team_preset": _PRESET,
                "message": "build it",
                "autonomous": True,
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201, start.text
        assert worker.dispatches
        assert worker.dispatches[-1]["feedback_batch_id"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_refusals_over_live_socket(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The v1 run-start refuses invalid requests before dispatch."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        # Empty prompt -> 422, no dispatch.
        empty = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-10",
                "team_preset": _PRESET,
                "message": "   ",
                **await _run_fields(client),
            },
        )
        assert empty.status_code == 422

        # Unknown / unloadable preset -> 422, no silent draft.
        unknown = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-11",
                "team_preset": "no-such-preset",
                "message": "go",
                **await _run_fields(client),
            },
        )
        assert unknown.status_code == 422

        # Document-authoring preset without a target feature -> 422.
        no_feature = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-12",
                "team_preset": "vaultspec-adr-research",
                "message": "research it",
                **await _run_fields(client),
            },
        )
        assert no_feature.status_code == 422
        assert "feature" in no_feature.json()["detail"]

        # Document-authoring preset with an incomplete token bundle -> 422.
        thin_bundle = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-13",
                "team_preset": "vaultspec-adr-research",
                "message": "research it",
                "feature_tag": "edge-feature",
                "actor_tokens": {
                    "tokens": {"vaultspec-researcher": "tok-r"},
                    "engine_bearer": "bearer",
                },
                **await _run_fields(client),
            },
        )
        assert thin_bundle.status_code == 422
        assert "token" in thin_bundle.json()["detail"]

        # Client ids must remain addressable by the path-based status, stream,
        # and cancel routes. Reject every ambiguous/path-breaking form at the
        # public gateway boundary before persistence or dispatch.
        for invalid_run_id in (
            "path/segment",
            "contains whitespace",
            "-leading-hyphen",
            "x" * 129,
        ):
            invalid_id = await client.post(
                "/v1/runs",
                json={
                    "team_preset": _PRESET,
                    "message": "go",
                    "run_id": invalid_run_id,
                    **await _run_fields(client),
                },
            )
            assert invalid_id.status_code == 422, invalid_run_id

        for method, target in (
            (client.get, "/v1/runs/-leading-hyphen"),
            (client.get, "/v1/runs/contains%20whitespace/stream"),
            (client.post, "/v1/runs/-leading-hyphen/cancel"),
        ):
            invalid_path = await method(target)
            assert invalid_path.status_code == 422, target

        dashboard_id = await client.post(
            "/v1/runs",
            json={
                "team_preset": _PRESET,
                "message": "go",
                "run_id": "run-0123456789abcdef0123456789abcdef",
                **await _run_fields(client),
            },
        )
        assert dashboard_id.status_code == 201
        assert dashboard_id.json()["run_id"] == "run-0123456789abcdef0123456789abcdef"

        # Only the valid dashboard-form id reached the worker.
        assert len(worker.dispatches) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_client_id_is_dispatch_exactly_once(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A retry with the same client run id returns the same run, dispatched once."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        payload = {
            "team_preset": _PRESET,
            "message": "build it",
            "autonomous": True,
            "run_id": "client-run-0001",
        }
        first = await client.post(
            "/v1/runs",
            json={"run_id": "gwlive-16", **payload, **await _run_fields(client)},
        )
        assert first.status_code == 201
        assert first.json()["run_id"] == "client-run-0001"

        second = await client.post(
            "/v1/runs",
            json={"run_id": "gwlive-17", **payload, **await _run_fields(client)},
        )
        assert second.status_code == 201
        assert second.json()["run_id"] == "client-run-0001"

        # Dispatched exactly once despite the retry.
        assert len(worker.dispatches) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_run_id_reservation_is_visible_before_dispatch_ack(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A concurrent retry observes one durable reservation and one dispatch."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    worker.hold_dispatch_response()
    payload = {
        "team_preset": _PRESET,
        "message": "build it",
        "autonomous": True,
        "run_id": "run-0123456789abcdef0123456789abcdef",
    }
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        first = asyncio.create_task(
            client.post(
                "/v1/runs",
                json={"run_id": "gwlive-18", **payload, **await _run_fields(client)},
            )
        )
        await asyncio.wait_for(worker.dispatch_received.wait(), timeout=5.0)

        status = await client.get(f"/v1/runs/{payload['run_id']}")
        assert status.status_code == 200
        assert status.json()["status"] == "submitted"

        replay = await client.post(
            "/v1/runs",
            json={"run_id": "gwlive-19", **payload, **await _run_fields(client)},
        )
        assert replay.status_code == 201
        assert replay.json()["run_id"] == payload["run_id"]
        assert len(worker.dispatches) == 1

        worker.release_dispatch.set()
        accepted = await first
        assert accepted.status_code == 201
        assert accepted.json()["run_id"] == payload["run_id"]
        assert len(worker.dispatches) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_sse_stream_delivers_versioned_event_mid_stream(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    run_id, _receipt = await _seed_live_thread(session_factory, title="live")

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        # One line iterator shared across both reads — aiter_lines consumes
        # the stream once, so a second call would raise StreamConsumed.
        lines = resp.aiter_lines()

        # Wait for the SSE handler to register its subscriber, then emit an
        # event into the same aggregator the live server is serving from.
        for _ in range(200):
            if agg.subscriber_count() > 0:
                break
            await asyncio.sleep(0.01)
        assert agg.subscriber_count() > 0, "SSE subscriber never registered"

        agg.relay_payload(
            run_id,
            {
                "type": "message_chunk",
                "event_type": "message_chunk",
                "thread_id": run_id,
                "message_id": "m-1",
                "content": "tick",
            },
        )

        progress = await _read_event(lines, wanted="message_chunk")
        assert progress["api_version"] == "v1"
        assert progress["type"] == "message_chunk"
        assert progress["content"] == "tick"

        # A terminal event closes the stream.
        agg.relay_payload(
            run_id,
            {
                "type": "thread_terminal",
                "event_type": "thread_terminal",
                "thread_id": run_id,
                "status": "completed",
            },
        )
        terminal = await _read_event(lines, wanted="thread_terminal")
        assert terminal["api_version"] == "v1"
        assert terminal["status"] == "completed"


@pytest.mark.asyncio(loop_scope="function")
async def test_sse_carries_semantic_phase_and_bounds_document_bodies(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Progress frames carry the semantic phase; oversized bodies bound.

    Bounding now has two layers, and both are exercised here: a document-sized
    artifact body is projected away by the closed per-event catalog, and a frame
    that is oversized through an identity key the catalog passes verbatim still
    degrades to the droppable sentinel at the byte cap.
    """
    from ...streaming.sse_frames import MAX_SSE_FRAME_BYTES

    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)

    run_id, _receipt = await _seed_live_thread(session_factory, title="live")

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        lines = resp.aiter_lines()
        for _ in range(200):
            if agg.subscriber_count() > 0:
                break
            await asyncio.sleep(0.01)
        assert agg.subscriber_count() > 0

        # A progress frame naming a research_adr node is stamped with the phase.
        agg.relay_payload(
            run_id,
            {
                "type": "agent_status",
                "event_type": "agent_status",
                "thread_id": run_id,
                "node_name": "synthesis",
                "state": "working",
            },
        )
        status_frame = await _read_event(lines, wanted="agent_status")
        assert status_frame["api_version"] == "v1"
        assert status_frame["semantic_phase"] == "synthesizing_research"

        # A document-body-sized artifact frame is bounded by the catalog: the
        # body is projected away, so the frame crosses as identity alone rather
        # than streaming the body verbatim.
        document_body = "D" * (MAX_SSE_FRAME_BYTES + 4096)
        agg.relay_payload(
            run_id,
            {
                "type": "artifact_update",
                "event_type": "artifact_update",
                "thread_id": run_id,
                "artifact_id": "art-1",
                "filename": "report.md",
                "content": document_body,
            },
        )
        artifact_frame = await _read_event(lines, wanted="artifact_update")
        assert artifact_frame["api_version"] == "v1"
        assert artifact_frame["artifact_id"] == "art-1"
        assert "content" not in artifact_frame

        # The byte cap is still the backstop for what the per-field caps cannot
        # bound - here an identity key, which the catalog passes verbatim.
        agg.relay_payload(
            run_id,
            {
                "type": "message_chunk",
                "event_type": "message_chunk",
                "thread_id": run_id,
                "message_id": "M" * (MAX_SSE_FRAME_BYTES + 4096),
                "content": "tick",
            },
        )
        dropped = await _read_event(lines, wanted="progress_dropped")
        assert dropped["api_version"] == "v1"
        assert dropped["dropped_type"] == "message_chunk"

        agg.relay_payload(
            run_id,
            {
                "type": "thread_terminal",
                "event_type": "thread_terminal",
                "thread_id": run_id,
                "status": "completed",
            },
        )
        terminal = await _read_event(lines, wanted="thread_terminal")
        assert terminal["status"] == "completed"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_stream_verb_reserves_versioned_frames(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """GET /v1/runs/{run_id}/stream re-serves the bounded, versioned v1 frames.

    The public run surface is the streaming companion to run-status: it delegates
    to the same stream builder the internal /api route uses, so the engine-facing
    edge sees the identical api_version stamp, mid-stream delivery, and
    terminal-replay-then-close semantics - no second code path.
    """
    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)
    run_id, _receipt = await _seed_live_thread(session_factory, title="run")

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = resp.aiter_lines()

        for _ in range(200):
            if agg.subscriber_count() > 0:
                break
            await asyncio.sleep(0.01)
        assert agg.subscriber_count() > 0, "run-stream subscriber never registered"

        agg.relay_payload(
            run_id,
            {
                "type": "message_chunk",
                "event_type": "message_chunk",
                "thread_id": run_id,
                "message_id": "m-1",
                "content": "tick",
            },
        )
        progress = await _read_event(lines, wanted="message_chunk")
        assert progress["api_version"] == "v1"
        assert progress["type"] == "message_chunk"
        assert progress["content"] == "tick"

        # A terminal event closes the run stream.
        agg.relay_payload(
            run_id,
            {
                "type": "thread_terminal",
                "event_type": "thread_terminal",
                "thread_id": run_id,
                "status": "completed",
            },
        )
        terminal = await _read_event(lines, wanted="thread_terminal")
        assert terminal["api_version"] == "v1"
        assert terminal["status"] == "completed"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_stream_unknown_run_is_404(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Streaming an unknown run id is a clean 404 in run vocabulary."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get("/v1/runs/does-not-exist/stream")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Run not found"


async def _read_event(
    lines: AsyncIterator[str], *, wanted: str, timeout: float = 5.0
) -> JsonObject:
    """Read SSE ``data:`` frames from *lines* until one whose ``type`` matches.

    Heartbeat frames (emitted on idle) are skipped. Raises on timeout so a
    broken stream fails the test instead of hanging it.
    """

    async def _scan() -> JsonObject:
        buffer: list[str] = []
        async for raw in lines:
            line = raw.rstrip("\r")
            if line.startswith("data: "):
                buffer.append(line.removeprefix("data: "))
                continue
            if line == "" and buffer:
                payload = cast("JsonObject", json.loads("".join(buffer)))
                buffer = []
                if payload.get("type") == wanted:
                    return payload
        raise AssertionError(f"stream ended before a {wanted!r} frame")

    return await asyncio.wait_for(_scan(), timeout=timeout)


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_freezes_and_discloses_catalog_selection(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Run start freezes the served selection and threads it to dispatch."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-20",
                "team_preset": _PRESET,
                "message": "go",
                "autonomous": True,
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201, start.text
        body = start.json()
        # What gets frozen and disclosed is the SELECTION. `profile_id` was the
        # old name for this fact and is no longer a run-start field at all, so
        # asserting it here would pin a contract the gateway stopped offering.
        frozen = body["frozen_assignment"]
        assert frozen, "run-start must disclose what it froze"
        # The effective assignments live INSIDE the freeze now. The top-level
        # `assignments` list is empty for a selection-driven run, so reading it
        # would assert nothing while appearing to check the disclosure.
        assert frozen["assignments"], "the freeze must name its assignments"
        first = frozen["assignments"][0]
        assert first["provider_id"]
        assert "api_key" not in start.text.lower() and "token" not in start.text.lower()

        # The dispatch carries the frozen assignment for the worker to compile against.
        dispatched = worker.dispatches[-1]
        assert dispatched["model_assignment"], "frozen assignment must reach dispatch"

        # Run status reproduces the exact frozen selection from durable metadata.
        status = await client.get(f"/v1/runs/{body['run_id']}")
        assert status.status_code == 200
        sbody = status.json()
        assert sbody["frozen_assignment"] == frozen, (
            "run-status must reproduce the freeze run-start disclosed"
        )
        assert "profile_id" not in sbody
        assert "assignments" not in sbody


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_rejects_retired_profile_field(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A retired profile field is refused with a 422 and never dispatched."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.post(
            "/v1/runs",
            json={
                "run_id": "gwlive-21",
                "team_preset": _PRESET,
                "message": "go",
                "profile_id": "ghost",
                **await _run_fields(client),
            },
        )
        # `profile_id` was removed when selections became explicit. The contract
        # forbids unknown fields rather than ignoring them, so a caller still
        # sending the retired one is told, instead of silently getting a run
        # configured by something other than what it asked for.
        assert resp.status_code == 422
        assert "profile_id" in resp.text
        assert worker.dispatches == [], "a refused body must not dispatch"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_conflicts_on_selection_request_change_retry(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A retry with changed work is a conflict rather than a silent replay."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        payload = {
            "team_preset": _PRESET,
            "message": "go",
            "run_id": "rid-conflict",
        }
        first = await client.post(
            "/v1/runs",
            json={"run_id": "gwlive-22", **payload, **await _run_fields(client)},
        )
        assert first.status_code == 201
        frozen = first.json()["frozen_assignment"]
        assert frozen

        # Same run id, DIFFERENT body -> conflict, not a replay. The changed
        # message is a different durable intention and must be refused.
        conflict = await client.post(
            "/v1/runs",
            json={
                **payload,
                "message": "a different intention",
                **await _run_fields(client),
            },
        )
        assert conflict.status_code == 409, conflict.text
        assert "different request body" in conflict.json()["detail"]

        # Same run id and same request -> idempotent replay returns the run.
        replay = await client.post(
            "/v1/runs",
            json={"run_id": "gwlive-24", **payload, **await _run_fields(client)},
        )
        assert replay.status_code == 201
        assert replay.json()["run_id"] == first.json()["run_id"]


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_replays_a_rotated_bundle_and_conflicts_on_a_changed_body(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Where the fingerprint draws the line between a retry and a new intention.

    Two verdicts, on the one durable run, over the real edge. A retry carrying
    freshly minted credentials is a RETRY: a replay returns the original run and
    never adopts the presented bundle, and short-lived tokens are expected to
    rotate between the lost acknowledgement and the retry, so refusing one would
    refuse exactly the recovery a client-supplied run id exists to serve. A retry
    carrying a different prompt is a NEW INTENTION wearing an old id and is
    refused, so it is never silently discarded as an idempotent replay.

    The catalog selection is held equal throughout - `_run_fields` is
    deterministic for a served catalog - so the digest branch is exercised by
    the one field that varies, the prompt.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        # Every post below shares this run id ON PURPOSE: the test is about
        # what a second request wearing an existing id is allowed to mean.
        payload = {
            "team_preset": _PRESET,
            "message": "go",
            "run_id": "rid-body-conflict",
            "actor_tokens": {
                "tokens": {"coder": "tok-minted"},
                "engine_bearer": "bearer-minted",
            },
        }
        first = await client.post(
            "/v1/runs",
            json={**payload, **await _run_fields(client)},
        )
        assert first.status_code == 201, first.text

        # Same run id, same work, FRESHLY MINTED credentials -> the original run.
        rotated = await client.post(
            "/v1/runs",
            json={
                **payload,
                "actor_tokens": {
                    "tokens": {"coder": "tok-rotated"},
                    "engine_bearer": "bearer-rotated",
                },
                **await _run_fields(client),
            },
        )
        assert rotated.status_code == 201, rotated.text
        assert rotated.json()["run_id"] == "rid-body-conflict"

        # Same run id, same selection, DIFFERENT prompt -> fingerprint conflict,
        # and the rotated bundle does not buy it a replay either.
        conflict = await client.post(
            "/v1/runs",
            json={
                **payload,
                "message": "a different intention",
                "actor_tokens": {
                    "tokens": {"coder": "tok-rotated"},
                    "engine_bearer": "bearer-rotated",
                },
                **await _run_fields(client),
            },
        )
        assert conflict.status_code == 409, conflict.text
        assert "different request body" in conflict.json()["detail"]

        # Neither the rotated replay nor the conflicting retry started a second
        # run: the replay returned the first dispatch, the conflict returned none.
        rid_dispatches = [
            d for d in worker.dispatches if d.get("thread_id") == "rid-body-conflict"
        ]
        assert len(rid_dispatches) == 1
        # The run kept the credentials it was STARTED with; a replay never
        # re-credentialed it with the bundle the retry presented.
        assert rid_dispatches[0]["actor_tokens"]["tokens"]["coder"] == "tok-minted"

        # An identical replay (the original body) still returns the original run,
        # proving the 409 was the changed body - not a blanket rejection.
        replay = await client.post(
            "/v1/runs",
            json={**payload, **await _run_fields(client)},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["run_id"] == "rid-body-conflict"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_idempotency_is_race_safe(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Concurrent same-run_id retries never 500: insert-or-return is atomic."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        payload = {"team_preset": _PRESET, "message": "go", "run_id": "rid-race"}
        # Resolved ONCE, outside the racing comprehension. Awaiting inside it
        # would make the argument an async generator rather than the iterable of
        # coroutines gather expects, and every racer must post a byte-identical
        # body for the idempotency this test is asserting to be the thing under
        # test rather than five different requests.
        raced_body = {**payload, **await _run_fields(client)}
        results = await asyncio.gather(
            *(client.post("/v1/runs", json=raced_body) for _ in range(5))
        )
        # No request races into a 5xx; every one resolves to the same single run.
        assert all(r.status_code == 201 for r in results), [
            r.status_code for r in results
        ]
        assert {r.json()["run_id"] for r in results} == {"rid-race"}
        # The winner dispatched exactly once; the losers returned it idempotently.
        raced = [d for d in worker.dispatches if d.get("thread_id") == "rid-race"]
        assert len(raced) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_modern_selection_insert_race_and_direct_replay_disclose_same_freeze(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both real insert-race recovery and later replay disclose durable authority."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    gate = admission_gate(app)
    run_id = "rid-modern-freeze-race"
    pool = engine.sync_engine.pool
    assert isinstance(pool, _CheckedOutPool)
    checked_out = pool.checkedout

    with caplog.at_level(logging.INFO, logger="vaultspec_a2a.api.routes.gateway"):
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=30.0) as client,
        ):
            selection, workspace_root = await _in_process_catalog_selection(client)
            responses, nickname_responses = await _run_modern_selection_races(
                client,
                engine,
                gate,
                checked_out,
                run_id,
                selection,
                workspace_root,
            )

    _assert_modern_race_results(
        responses,
        nickname_responses,
        caplog=caplog,
        worker=worker,
        run_id=run_id,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_concurrent_same_run_id_different_bodies_conflicts(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The loser of a real insert race is refused when its body differs.

    The sequential retry path compares the whole request before answering with
    the durable run. Two genuinely simultaneous requests skip that comparison
    unless the insert-race branch applies it too: both read no run, both insert,
    and the loser's primary-key violation resolves to the winner. Without the
    same check there, a racer carrying a different prompt is told its run started
    and handed the winner's id, its own intention silently dropped.

    The race is driven for real, not simulated. A second connection holds
    SQLite's write lock (``BEGIN IMMEDIATE``), so both requests complete their
    check-then-act read while the run genuinely does not exist and both then
    block at the insert; releasing the lock lets exactly one insert win and
    drives the other into the integrity branch. The branch's own log record is
    asserted, so this test cannot pass on the sequential path.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    gate = admission_gate(app)
    run_id = "rid-race-conflict"
    # The run id is deliberately SHARED and the message deliberately differs:
    # that pairing is the whole subject, since the loser of the insert race must
    # be refused precisely because its body differs from the winner's.
    shared = {
        "team_preset": _PRESET,
        "run_id": run_id,
        "autonomous": True,
    }
    first_body = {**shared, "message": "first intention"}
    second_body = {**shared, "message": "second intention"}
    pool = engine.sync_engine.pool
    assert isinstance(pool, _CheckedOutPool)
    checked_out = pool.checkedout

    with caplog.at_level(logging.INFO, logger="vaultspec_a2a.api.routes.gateway"):
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=30.0) as client,
        ):
            race = await _run_different_body_race(
                client,
                engine,
                gate,
                checked_out,
                run_id,
                first_body,
                second_body,
            )

    await _assert_different_body_race(
        race,
        session_factory=session_factory,
        worker=worker,
        gate=gate,
        caplog=caplog,
        run_id=run_id,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_pairing_identity_is_authenticated_surface_only(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """The gateway's lifetime identity never reaches an ungated health body.

    Under the Compose and development profiles ``GET /health`` is
    unauthenticated and serves the full readiness aggregate - the very dict the
    pairing echo is assembled into - verbatim. The gateway's lifetime identity
    must not ride along: the armed adoption check trusts a worker's reported
    lifetime precisely because a port squatter cannot guess it, so publishing it
    to anonymous callers would hand over the one value that check depends on.

    Discriminating on both halves of the boundary in ONE application, so
    neither half can pass vacuously: the same worker probe result is served
    WITH the identity on the attach-authenticated readiness verb and WITHOUT it
    on the ungated one. Drop the ``include_pairing`` gate - assemble the pairing
    evidence into the aggregate unconditionally - and the health assertions
    below fail while the service-state ones still pass.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        # The ungated probe surface, serving the unarmed full body rather than a
        # liveness stub, so the absences asserted against it are absences from a
        # payload that demonstrably carries the rest of the probe's findings.
        health = await client.get("/health")
        assert health.status_code == 200
        hbody = health.json()
        assert hbody["service"] == "gateway", hbody
        assert "checks" in hbody, hbody
        assert hbody["checks"]["worker"]["status"] == "ok", hbody
        assert "worker_status" in hbody, hbody
        assert "worker_paired_gateway_lifetime" not in hbody, hbody
        assert "worker_reported_generation" not in hbody, hbody
        assert "gateway_lifetime_id" not in hbody, hbody

        # Served here, off the very same probe path that produced the two
        # bodies above: the difference is the authentication boundary, not the
        # availability of the evidence.
        service = await client.get("/v1/service")
        assert service.status_code == 200
        sbody = service.json()
        assert isinstance(sbody["gateway_lifetime_id"], str)
        assert sbody["gateway_lifetime_id"].strip(), sbody
        assert sbody["worker_ready"] is True, sbody
