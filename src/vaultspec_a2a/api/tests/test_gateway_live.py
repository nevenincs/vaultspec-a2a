"""Live gateway coverage for the five verbs and the SSE stream (ADR R6).

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
import contextlib
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn

from ...streaming.aggregator import EventAggregator
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_PRESET = "mock-success-single"


@contextlib.asynccontextmanager
async def _live_server(app) -> AsyncIterator[str]:
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
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio(loop_scope="function")
async def test_five_verbs_over_live_socket(session_factory, checkpointer) -> None:
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        # presets-list
        presets = await client.get("/v1/presets")
        assert presets.status_code == 200
        pbody = presets.json()
        assert pbody["api_version"] == "v1"
        assert any(p["id"] == _PRESET for p in pbody["presets"])

        # service-state
        service = await client.get("/v1/service")
        assert service.status_code == 200
        sbody = service.json()
        assert sbody["api_version"] == "v1"
        # Status is probe-derived, not hardcoded: the in-process worker /health,
        # real DB, and real checkpointer all answer, so the service is ready.
        assert sbody["status"] == "ready"
        assert isinstance(sbody["ready"], bool)

        # run-start (carries the R7 actor token bundle)
        start = await client.post(
            "/v1/runs",
            json={
                "team_preset": _PRESET,
                "message": "build it",
                "autonomous": True,
                "actor_tokens": {
                    "tokens": {"coder": "tok-coder"},
                    "engine_bearer": "bearer",
                },
            },
        )
        assert start.status_code == 201
        stbody = start.json()
        assert stbody["api_version"] == "v1"
        run_id = stbody["run_id"]
        assert run_id
        # The worker received the dispatch carrying the tokens (transport).
        assert worker.dispatches, "run-start must dispatch to the worker"
        assert worker.dispatches[-1]["actor_tokens"]["tokens"]["coder"] == "tok-coder"

        # run-status recovery snapshot
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

        # unknown run -> 404
        missing = await client.get("/v1/runs/does-not-exist")
        assert missing.status_code == 404

        # run-cancel is idempotent: two calls both succeed
        first = await client.post(f"/v1/runs/{run_id}/cancel")
        assert first.status_code == 200
        assert first.json()["api_version"] == "v1"
        second = await client.post(f"/v1/runs/{run_id}/cancel")
        assert second.status_code == 200


@pytest.mark.asyncio(loop_scope="function")
async def test_service_state_degrades_when_circuit_breaker_opens(
    session_factory, checkpointer
) -> None:
    """A real dependency failure (open circuit) degrades service-state (P03.S06).

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
async def test_run_status_carries_reconnect_cursor(
    session_factory, checkpointer
) -> None:
    """run-status carries the monotonic last_sequence reconnect cursor (P03.S06).

    Evidence battery, SSE reconnect with non-authoritative semantics: durable
    reconnect reconciliation comes from run-status (last_sequence), not from the
    droppable SSE progress stream. This asserts the cursor is served.
    """
    from ...database.thread_repository import create_thread
    from ...thread.enums import ThreadStatus

    async with session_factory() as session:
        thread = await create_thread(
            session, status=ThreadStatus.RUNNING, title="cursor"
        )
        await session.commit()
        run_id = thread.id

    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get(f"/v1/runs/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "last_sequence" in body
        assert isinstance(body["last_sequence"], int)


@pytest.mark.asyncio(loop_scope="function")
async def test_service_state_is_probe_backed_and_distinguishes_readiness(
    session_factory, checkpointer
) -> None:
    """service-state reports truthful probe-derived readiness fields (P01.S03)."""
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
    session_factory, checkpointer, tmp_path
) -> None:
    """presets-list marks loadable/unloadable and survives one bad preset (P01.S02)."""
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
        assert by_id["broken-preset"]["unavailable_reason"]

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

        # model-profiles: origin, supported outputs, and the profile set.
        assert authoring["origin"] == "bundled"
        assert authoring["supported_capabilities"] == [
            "research_document",
            "architecture_decision",
        ]
        assert authoring["default_profile_id"] == "team-defaults"
        profiles = {p["id"]: p for p in authoring["profiles"]}
        assert set(profiles) == {"team-defaults", "fast"}
        assert profiles["team-defaults"]["is_default"] is True

        # team-defaults effective assignments: safe operational fields only, and
        # the resolver's real heterogeneity is disclosed (doc-reviewer differs).
        td_by_agent = {
            a["agent_id"]: a for a in profiles["team-defaults"]["assignments"]
        }
        researcher = td_by_agent["vaultspec-researcher"]
        assert researcher["provider_id"] == "claude"
        assert researcher["model_name"]  # a concrete, stable name
        assert researcher["role_id"] == "researcher"
        assert "capability" in researcher
        assert td_by_agent["vaultspec-doc-reviewer"]["provider_id"] == "zhipu"

        # fast lowers the researcher to a low capability and attributes the change
        # to the profile; the authoring roles fall through unchanged.
        fast_by_agent = {a["agent_id"]: a for a in profiles["fast"]["assignments"]}
        assert fast_by_agent["vaultspec-researcher"]["capability"] == "low"
        assert fast_by_agent["vaultspec-researcher"]["source"] == "profile"
        assert fast_by_agent["vaultspec-synthesist"]["source"] == "agent"

        # Eligibility is reported honestly: the production acceptance gate is open,
        # so every profile is unavailable with a safe reason (no secrets anywhere).
        for profile in profiles.values():
            assert profile["eligible"] is False
            assert any("acceptance gate" in r for r in profile["unavailable_reasons"])

        # No credential/token/env material appears anywhere in the served record.
        raw = resp.text.lower()
        for secret_marker in ("api_key", "oauth", "token", "secret", "password"):
            assert secret_marker not in raw


@pytest.mark.asyncio(loop_scope="function")
async def test_presets_list_discloses_workspace_profile_origin(
    session_factory, checkpointer, tmp_path
) -> None:
    """A workspace-local preset with a profile is served with origin=workspace."""
    teams_dir = tmp_path / ".vaultspec" / "teams"
    teams_dir.mkdir(parents=True)
    (teams_dir / "ws-team.toml").write_text(
        "\n".join(
            [
                "[team]",
                'id = "ws-team"',
                'display_name = "WS Team"',
                "[team.defaults]",
                'provider = "mock"',
                "[team.topology]",
                'type = "star"',
                "[[team.workers]]",
                'agent_id = "vaultspec-researcher"',
                "[team.profiles.fast]",
                'display_name = "Fast"',
                "[team.profiles.fast.roles.vaultspec-researcher]",
                'provider = "mock"',
                'capability = "low"',
            ]
        ),
        encoding="utf-8",
    )
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.get("/v1/presets", params={"workspace_root": str(tmp_path)})
        assert resp.status_code == 200
        by_id = {p["id"]: p for p in resp.json()["presets"]}
        ws_team = by_id["ws-team"]
        assert ws_team["origin"] == "workspace"
        profiles = {p["id"]: p for p in ws_team["profiles"]}
        assert set(profiles) == {"team-defaults", "fast"}
        # The mock-provider role is ready, so eligibility fails only on the open
        # acceptance gate / engine reachability, never on a mock credential.
        fast = {a["agent_id"]: a for a in profiles["fast"]["assignments"]}
        assert fast["vaultspec-researcher"]["provider_id"] == "mock"
        assert fast["vaultspec-researcher"]["provider_ready"] is True
        assert fast["vaultspec-researcher"]["capability"] == "low"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_refusals_over_live_socket(
    session_factory, checkpointer
) -> None:
    """The v1 run-start refuses invalid requests before dispatch (P01.S01)."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        # Empty prompt -> 422, no dispatch.
        empty = await client.post(
            "/v1/runs", json={"team_preset": _PRESET, "message": "   "}
        )
        assert empty.status_code == 422

        # Unknown / unloadable preset -> 422, no silent draft.
        unknown = await client.post(
            "/v1/runs", json={"team_preset": "no-such-preset", "message": "go"}
        )
        assert unknown.status_code == 422

        # Document-authoring preset without a target feature -> 422.
        no_feature = await client.post(
            "/v1/runs",
            json={"team_preset": "vaultspec-adr-research", "message": "research it"},
        )
        assert no_feature.status_code == 422
        assert "feature" in no_feature.json()["detail"]

        # Document-authoring preset with an incomplete token bundle -> 422.
        thin_bundle = await client.post(
            "/v1/runs",
            json={
                "team_preset": "vaultspec-adr-research",
                "message": "research it",
                "feature_tag": "edge-feature",
                "actor_tokens": {
                    "tokens": {"vaultspec-researcher": "tok-r"},
                    "engine_bearer": "bearer",
                },
            },
        )
        assert thin_bundle.status_code == 422
        assert "token" in thin_bundle.json()["detail"]

        # None of the refusals reached the worker.
        assert worker.dispatches == []


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_client_id_is_dispatch_exactly_once(
    session_factory, checkpointer
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
        first = await client.post("/v1/runs", json=payload)
        assert first.status_code == 201
        assert first.json()["run_id"] == "client-run-0001"

        second = await client.post("/v1/runs", json=payload)
        assert second.status_code == 201
        assert second.json()["run_id"] == "client-run-0001"

        # Dispatched exactly once despite the retry.
        assert len(worker.dispatches) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_sse_stream_delivers_versioned_event_mid_stream(
    session_factory, checkpointer
) -> None:
    from ...database.thread_repository import create_thread
    from ...thread.enums import ThreadStatus

    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)

    async with session_factory() as session:
        thread = await create_thread(session, status=ThreadStatus.RUNNING, title="live")
        await session.commit()
        run_id = thread.id

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/api/threads/{run_id}/stream") as resp,
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
                "type": "progress",
                "event_type": "progress",
                "thread_id": run_id,
                "step": 1,
            },
        )

        progress = await _read_event(lines, wanted="progress")
        assert progress["api_version"] == "v1"
        assert progress["type"] == "progress"
        assert progress["step"] == 1

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
    session_factory, checkpointer
) -> None:
    """Progress frames carry the semantic phase; oversized bodies bound (P02.S05)."""
    from ...database.thread_repository import create_thread
    from ...streaming.sse_frames import MAX_SSE_FRAME_BYTES
    from ...thread.enums import ThreadStatus

    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)

    async with session_factory() as session:
        thread = await create_thread(session, status=ThreadStatus.RUNNING, title="live")
        await session.commit()
        run_id = thread.id

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        client.stream("GET", f"/api/threads/{run_id}/stream") as resp,
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

        # A document-body-sized frame is bounded: it degrades to a droppable
        # sentinel rather than streaming the body verbatim.
        agg.relay_payload(
            run_id,
            {
                "type": "artifact",
                "event_type": "artifact",
                "thread_id": run_id,
                "content": "D" * (MAX_SSE_FRAME_BYTES + 4096),
            },
        )
        dropped = await _read_event(lines, wanted="progress_dropped")
        assert dropped["api_version"] == "v1"
        assert dropped["dropped_type"] == "artifact"

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


async def _read_event(
    lines: AsyncIterator[str], *, wanted: str, timeout: float = 5.0
) -> dict:
    """Read SSE ``data:`` frames from *lines* until one whose ``type`` matches.

    Heartbeat frames (emitted on idle) are skipped. Raises on timeout so a
    broken stream fails the test instead of hanging it.
    """

    async def _scan() -> dict:
        buffer: list[str] = []
        async for raw in lines:
            line = raw.rstrip("\r")
            if line.startswith("data: "):
                buffer.append(line.removeprefix("data: "))
                continue
            if line == "" and buffer:
                payload = json.loads("".join(buffer))
                buffer = []
                if payload.get("type") == wanted:
                    return payload
        raise AssertionError(f"stream ended before a {wanted!r} frame")

    return await asyncio.wait_for(_scan(), timeout=timeout)
