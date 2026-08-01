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
import contextlib
import json
import logging
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn

from ...database import list_threads
from ...graph.enums import Provider
from ...providers.model_profiles import probe_provider_readiness
from ...streaming.aggregator import EventAggregator
from ..routes.gateway import _persisted_lease_id, admission_gate
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

_PRESET = "mock-success-single"


async def _seed_permission(session_factory, *, thread_id: str, request_id: str) -> None:
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
    session_factory, checkpointer
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
                "team_preset": _PRESET,
                "message": "remember this",
                "autonomous": True,
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
    session_factory, checkpointer
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
            json={"team_preset": _PRESET, "message": "work", "autonomous": True},
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
    session_factory, checkpointer
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
    session_factory, checkpointer
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

        async def _start(message: str) -> str:
            resp = await client.post(
                "/v1/runs",
                json={"team_preset": _PRESET, "message": message, "autonomous": True},
            )
            assert resp.status_code == 201
            return resp.json()["run_id"]

        owner = await _start("owns the permission")
        stranger = await _start("owns nothing")
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


def test_legacy_lease_only_metadata_remains_status_visible() -> None:
    """The additive status reader preserves the preceding persisted shape."""
    legacy = json.dumps({"run_lease": {"lease_id": "lease-legacy123"}})
    assert _persisted_lease_id(legacy) == "lease-legacy123"
    assert _persisted_lease_id('{"run_lease":{"lease_id":"not/addressable"}}') is None


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
async def test_run_status_carries_reconnect_cursor(
    session_factory, checkpointer
) -> None:
    """run-status carries the monotonic last_sequence reconnect cursor.

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
    session_factory, checkpointer, tmp_path
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

        # model-profiles: origin, supported outputs, and the profile set.
        assert authoring["origin"] == "bundled"
        assert authoring["supported_capabilities"] == [
            "research_document",
            "architecture_decision",
            "plan_document",
        ]
        assert authoring["default_profile_id"] == "team-defaults"
        profiles = {p["id"]: p for p in authoring["profiles"]}
        assert set(profiles) == {
            "team-defaults",
            "fast",
            "codex",
            "codex-all",
            "zai",
            "kimi",
            "kimi-all",
            "gemini",
            "openai",
            "zhipu",
        }
        assert profiles["team-defaults"]["is_default"] is True

        # team-defaults effective assignments: safe operational fields only. All
        # five document personas resolve to the Claude subscription tier (the
        # doc-reviewer was repinned off the non-resolving zhipu fallback);
        # provider heterogeneity is instead disclosed by the codex/zai
        # provider-axis profiles asserted below.
        td_by_agent = {
            a["agent_id"]: a for a in profiles["team-defaults"]["assignments"]
        }
        researcher = td_by_agent["vaultspec-researcher"]
        assert researcher["provider_id"] == "claude"
        assert researcher["model_name"]  # a concrete, stable name
        assert researcher["role_id"] == "researcher"
        assert "capability" in researcher
        assert td_by_agent["vaultspec-doc-reviewer"]["provider_id"] == "claude"

        # fast lowers the researcher to a low capability and attributes the change
        # to the profile; the authoring roles fall through unchanged.
        fast_by_agent = {a["agent_id"]: a for a in profiles["fast"]["assignments"]}
        assert fast_by_agent["vaultspec-researcher"]["capability"] == "low"
        assert fast_by_agent["vaultspec-researcher"]["source"] == "profile"
        assert fast_by_agent["vaultspec-synthesist"]["source"] == "agent"

        # Provider axis: the discovery response
        # surfaces the new providers per role. `codex` overlays codex on the three
        # research/authoring roles; `zai` overlays zai. The overlay attribution
        # (source == "profile") is disclosed and the un-overlaid doc-reviewer falls
        # through to a different provider - a genuinely mixed profile.
        authoring_roles = (
            "vaultspec-researcher",
            "vaultspec-synthesist",
            "vaultspec-adr-author",
            "vaultspec-planner",
        )
        codex_by_agent = {a["agent_id"]: a for a in profiles["codex"]["assignments"]}
        for agent_id in authoring_roles:
            assert codex_by_agent[agent_id]["provider_id"] == "codex"
            assert codex_by_agent[agent_id]["source"] == "profile"
        assert codex_by_agent["vaultspec-doc-reviewer"]["provider_id"] != "codex"

        # The single-provider lanes are the inverse of the mixed ones: every
        # worker, doc-reviewer included, is overlaid, so a run on them consumes
        # exactly one provider's credential. Asserting the doc-reviewer here is
        # the load-bearing part - it is the role the mixed lanes leave behind,
        # and the reason a provider-only proof cannot be expressed on them.
        all_roles = (*authoring_roles, "vaultspec-doc-reviewer")
        for profile_id, provider_id in (("codex-all", "codex"), ("kimi-all", "kimi")):
            by_agent = {a["agent_id"]: a for a in profiles[profile_id]["assignments"]}
            assert set(by_agent) == set(all_roles)
            for agent_id in all_roles:
                assert by_agent[agent_id]["provider_id"] == provider_id
                assert by_agent[agent_id]["source"] == "profile"

        zai_by_agent = {a["agent_id"]: a for a in profiles["zai"]["assignments"]}
        zai_readiness = probe_provider_readiness(Provider.ZAI)
        for agent_id in authoring_roles:
            assert zai_by_agent[agent_id]["provider_id"] == "zai"
            assert zai_by_agent[agent_id]["source"] == "profile"
            assert zai_by_agent[agent_id]["provider_ready"] is zai_readiness.ready
        # Readiness reflects the real host. When Z.ai is unavailable, discovery
        # must carry the same safe production-probe reason without exposing a
        # credential value.
        if not zai_readiness.ready:
            assert zai_readiness.reason
            # The reason must be carried, but the serving layer is free to nest it
            # inside a composed role-eligibility entry: on a host whose agent
            # harness is incomplete the provider reason arrives folded into that
            # larger entry rather than standing alone.
            assert any(
                zai_readiness.reason in entry
                for entry in profiles["zai"]["unavailable_reasons"]
            )

        # Agent-panel P09.S34: the kimi/gemini/openai/zhipu mixed lanes are the
        # exact structural siblings of zai above - same honest-readiness
        # discipline, same nested-reason carrying on an incomplete host.
        for profile_id, provider in (
            ("kimi", Provider.KIMI),
            ("gemini", Provider.GEMINI),
            ("openai", Provider.OPENAI),
            ("zhipu", Provider.ZHIPU),
        ):
            by_agent = {
                a["agent_id"]: a for a in profiles[profile_id]["assignments"]
            }
            readiness = probe_provider_readiness(provider)
            for agent_id in authoring_roles:
                assert by_agent[agent_id]["provider_id"] == profile_id
                assert by_agent[agent_id]["source"] == "profile"
                assert by_agent[agent_id]["provider_ready"] is readiness.ready
            if not readiness.ready:
                assert readiness.reason
                assert any(
                    readiness.reason in entry
                    for entry in profiles[profile_id]["unavailable_reasons"]
                )

        # Eligibility is reported honestly: the production acceptance gate is open,
        # so every profile is unavailable with a safe reason (no secrets anywhere).
        for profile in profiles.values():
            assert profile["eligible"] is False
            assert any("acceptance gate" in r for r in profile["unavailable_reasons"])

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
async def test_run_envelope_and_presets_list_agree_on_provider_readiness(
    session_factory, checkpointer
) -> None:
    """One question, one answer: readiness cannot differ by which verb is asked.

    ``RoleAssignmentSummary`` is constructed in exactly two places - the preset
    listing, which probes readiness live, and the run envelope, which is
    assembled from the frozen assignment. The run envelope set every field but
    ``provider_ready`` and so inherited the model's ``False`` default: a run
    started on a provider the listing had just advertised as ready came back
    reporting it unready. A Pydantic default cannot fail, which is exactly why
    nothing caught it.

    The assertion is agreement between the two disclosures, with each side
    independently anchored to the production probe so they cannot pass by being
    wrong in the same way.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        presets = await client.get("/v1/presets")
        assert presets.status_code == 200
        preset = next(p for p in presets.json()["presets"] if p["id"] == _PRESET)
        profile = next(
            pr for pr in preset["profiles"] if pr["id"] == preset["default_profile_id"]
        )
        listed = {a["agent_id"]: a for a in profile["assignments"]}
        assert listed, "the listing must disclose the default profile's assignments"

        # Anchor the listing to the real probe first, so "the two agree" below
        # cannot be satisfied by both sides sharing a single wrong answer.
        for assignment in listed.values():
            probed = probe_provider_readiness(Provider(assignment["provider_id"]))
            assert assignment["provider_ready"] is probed.ready

        start = await client.post(
            "/v1/runs",
            json={"team_preset": _PRESET, "message": "work", "autonomous": True},
        )
        assert start.status_code == 201
        run_id = start.json()["run_id"]

        status = await client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200

        # Both run-envelope disclosures - the start response and the polled
        # status read, which rebuilds from persisted metadata - must answer for
        # a role's provider exactly as the listing did.
        for source, envelope in (
            ("run-start", start.json()),
            ("run-status", status.json()),
        ):
            disclosed = {a["agent_id"]: a for a in envelope["assignments"]}
            assert set(disclosed) == set(listed), source
            for agent_id, assignment in disclosed.items():
                assert assignment["provider_id"] == listed[agent_id]["provider_id"], (
                    source
                )
                assert (
                    assignment["provider_ready"] is listed[agent_id]["provider_ready"]
                ), source


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_threads_feedback_batch_id_to_worker(
    session_factory, checkpointer, tmp_path
) -> None:
    """The opaque feedback_batch_id threads run-start -> metadata -> worker dispatch.

    Feedback-loop carrier (edge ADR D5): a2a transports the opaque id only. The
    run-start body carries it, the gateway folds it onto the run metadata, and the
    dispatch the worker receives carries it verbatim - the same path active_feature
    rides. a2a never parses the id; retrieval is the worker's engine read.
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
                "message": "revise the draft",
                "autonomous": True,
                "feedback_batch_id": "feedback-batch:deadbeefcafe",
                "metadata": {"workspace_root": str(tmp_path)},
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
    session_factory, checkpointer, tmp_path
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
                "team_preset": _PRESET,
                "message": "build it",
                "autonomous": True,
                "metadata": {"workspace_root": str(tmp_path)},
            },
        )
        assert start.status_code == 201, start.text
        assert worker.dispatches
        assert worker.dispatches[-1]["feedback_batch_id"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_refusals_over_live_socket(
    session_factory, checkpointer
) -> None:
    """The v1 run-start refuses invalid requests before dispatch."""
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
            },
        )
        assert dashboard_id.status_code == 201
        assert dashboard_id.json()["run_id"] == "run-0123456789abcdef0123456789abcdef"

        # Only the valid dashboard-form id reached the worker.
        assert len(worker.dispatches) == 1


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
async def test_run_id_reservation_is_visible_before_dispatch_ack(
    session_factory, checkpointer
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
        first = asyncio.create_task(client.post("/v1/runs", json=payload))
        await asyncio.wait_for(worker.dispatch_received.wait(), timeout=5.0)

        status = await client.get(f"/v1/runs/{payload['run_id']}")
        assert status.status_code == 200
        assert status.json()["status"] == "submitted"

        replay = await client.post("/v1/runs", json=payload)
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
    session_factory, checkpointer
) -> None:
    """Progress frames carry the semantic phase; oversized bodies bound.

    Bounding now has two layers, and both are exercised here: a document-sized
    artifact body is projected away by the closed per-event catalog, and a frame
    that is oversized through an identity key the catalog passes verbatim still
    degrades to the droppable sentinel at the byte cap.
    """
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
    session_factory, checkpointer
) -> None:
    """GET /v1/runs/{run_id}/stream re-serves the bounded, versioned v1 frames.

    The public run surface is the streaming companion to run-status: it delegates
    to the same stream builder the internal /api route uses, so the engine-facing
    edge sees the identical api_version stamp, mid-stream delivery, and
    terminal-replay-then-close semantics - no second code path.
    """
    from ...database.thread_repository import create_thread
    from ...thread.enums import ThreadStatus

    aggregator = EventAggregator()
    app, agg, _worker, _cp = make_app(session_factory, checkpointer, aggregator)

    async with session_factory() as session:
        thread = await create_thread(session, status=ThreadStatus.RUNNING, title="run")
        await session.commit()
        run_id = thread.id

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
async def test_run_stream_unknown_run_is_404(session_factory, checkpointer) -> None:
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


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_freezes_and_discloses_profile(
    session_factory, checkpointer
) -> None:
    """run-start freezes the default profile, threads it to dispatch, discloses it."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={"team_preset": _PRESET, "message": "go", "autonomous": True},
        )
        assert start.status_code == 201, start.text
        body = start.json()
        # The default profile is frozen and disclosed with its assignments.
        assert body["profile_id"] == "team-defaults"
        assert body["assignments"], "run-start must disclose effective assignments"
        first = body["assignments"][0]
        assert first["provider_id"]
        assert "api_key" not in start.text.lower() and "token" not in start.text.lower()

        # The dispatch carries the frozen assignment for the worker to compile against.
        dispatched = worker.dispatches[-1]
        assert dispatched["profile_id"] == "team-defaults"
        assert dispatched["model_assignment"], "frozen assignment must reach dispatch"

        # run-status reproduces the frozen profile + assignments from run metadata.
        status = await client.get(f"/v1/runs/{body['run_id']}")
        assert status.status_code == 200
        sbody = status.json()
        assert sbody["profile_id"] == "team-defaults"
        assert sbody["assignments"]


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_rejects_unknown_profile(session_factory, checkpointer) -> None:
    """An unknown profile is refused with a 422 and never dispatched."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        resp = await client.post(
            "/v1/runs",
            json={"team_preset": _PRESET, "message": "go", "profile_id": "ghost"},
        )
        assert resp.status_code == 422
        assert "profile" in resp.json()["detail"].lower()
        assert worker.dispatches == [], "an unknown profile must not dispatch"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_conflicts_on_profile_change_retry(
    session_factory, checkpointer
) -> None:
    """A retry that changes the frozen profile is a 409, never a silent replay."""
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
        first = await client.post("/v1/runs", json=payload)
        assert first.status_code == 201
        assert first.json()["profile_id"] == "team-defaults"

        # Same run id, different profile -> conflict, not a replay.
        conflict = await client.post(
            "/v1/runs", json={**payload, "profile_id": "other-profile"}
        )
        assert conflict.status_code == 409
        assert "already started with profile" in conflict.json()["detail"]

        # Same run id, same (default) profile -> idempotent replay returns the run.
        replay = await client.post("/v1/runs", json=payload)
        assert replay.status_code == 201
        assert replay.json()["run_id"] == first.json()["run_id"]


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_replays_a_rotated_bundle_and_conflicts_on_a_changed_body(
    session_factory, checkpointer
) -> None:
    """Where the fingerprint draws the line between a retry and a new intention.

    Two verdicts, on the one durable run, over the real edge. A retry carrying
    freshly minted credentials is a RETRY: a replay returns the original run and
    never adopts the presented bundle, and short-lived tokens are expected to
    rotate between the lost acknowledgement and the retry, so refusing one would
    refuse exactly the recovery a client-supplied run id exists to serve. A retry
    carrying a different prompt is a NEW INTENTION wearing an old id and is
    refused, so it is never silently discarded as an idempotent replay.

    The profile is held equal to the frozen default throughout so the digest
    branch - not the profile branch - is the one exercised.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        payload = {
            "team_preset": _PRESET,
            "message": "go",
            "run_id": "rid-body-conflict",
            "profile_id": "team-defaults",
            "actor_tokens": {
                "tokens": {"coder": "tok-minted"},
                "engine_bearer": "bearer-minted",
            },
        }
        first = await client.post("/v1/runs", json=payload)
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
            },
        )
        assert rotated.status_code == 201, rotated.text
        assert rotated.json()["run_id"] == "rid-body-conflict"

        # Same run id, same profile, DIFFERENT prompt -> fingerprint conflict,
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
        replay = await client.post("/v1/runs", json=payload)
        assert replay.status_code == 201, replay.text
        assert replay.json()["run_id"] == "rid-body-conflict"


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_idempotency_is_race_safe(
    session_factory, checkpointer
) -> None:
    """Concurrent same-run_id retries never 500: insert-or-return is atomic."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        payload = {"team_preset": _PRESET, "message": "go", "run_id": "rid-race"}
        results = await asyncio.gather(
            *(client.post("/v1/runs", json=payload) for _ in range(5))
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
async def test_concurrent_same_run_id_different_bodies_conflicts(
    engine, session_factory, checkpointer, caplog: pytest.LogCaptureFixture
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
    shared = {
        "team_preset": _PRESET,
        "run_id": run_id,
        "profile_id": "team-defaults",
        "autonomous": True,
    }
    first_body = {**shared, "message": "first intention"}
    second_body = {**shared, "message": "second intention"}
    checked_out = engine.sync_engine.pool.checkedout

    with caplog.at_level(logging.INFO, logger="vaultspec_a2a.api.routes.gateway"):
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=30.0) as client,
        ):
            barrier = await engine.connect()
            baseline = checked_out()
            await barrier.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                first = asyncio.create_task(client.post("/v1/runs", json=first_body))
                # Admission happens after the check-then-act read and before the
                # insert, so an active run id proves the first request read an
                # absent run and is now held at the barrier.
                await _wait_until(
                    lambda: gate.is_active(run_id),
                    what="the first request to pass its read",
                )
                second = asyncio.create_task(client.post("/v1/runs", json=second_body))
                # A second leased connection proves the second request is issuing
                # DB work of its own - its read, which can only miss while the
                # barrier bars every insert.
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
            # The refusal is specific to the colliding body, not a blanket
            # rejection of the raced id: the winner's own request still replays.
            replay = await client.post("/v1/runs", json=winning_body)

    assert sorted(r.status_code for r in (winner, loser)) == [201, 409], [
        winner.text,
        loser.text,
    ]
    # Proof the refusal came from the insert-race branch and not the sequential
    # check-then-act one: only the integrity path records the lost race.
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

    # The refused racer left no second run, and only the winner's intention was
    # ever dispatched.
    async with session_factory() as verify:
        _rows, total = await list_threads(verify)
    assert total == 1
    raced = [d for d in worker.dispatches if d.get("thread_id") == run_id]
    assert len(raced) == 1
    assert raced[0]["content"] == winning_body["message"]

    # The durable winner keeps its admission: the refused loser must not release
    # the drain gate's active run out from under the run that owns it.
    assert gate.is_active(run_id)


@pytest.mark.asyncio(loop_scope="function")
async def test_pairing_identity_is_authenticated_surface_only(
    session_factory, checkpointer
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
