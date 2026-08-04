"""Real authenticated-stream proofs for the closed progress catalog.

The public ``/v1/runs/{run_id}/stream`` edge is a closed per-event catalog: it
relays a run's identifiers, lifecycle, tool and artifact identity, and bounded
text, and it must never relay a prompt, document or artifact body, edit diff, raw
provider payload, or the free-form ``metadata`` dict. A frame type absent from
the catalog is degraded to its identity keys rather than relayed. It is also
bounded: an authenticated caller cannot open an unbounded number of streams.

These drive the real edge over a real TCP socket behind the production discovery
bearer - no mocks, no auth bypass - relaying forbidden content into the same
aggregator the live server reads from and asserting it never crosses the encoded
boundary while the permitted fields do. Every exclusion assertion is paired with
a permitted-field assertion, so an empty or dropped frame cannot satisfy it.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from ...control.config import settings
from ...streaming.aggregator import EventAggregator
from ...streaming.sse_frames import MAX_PROGRESS_CONTENT_CHARS
from ...testing.sse import read_frame
from ...thread.enums import ThreadStatus
from .conftest import _live_server, make_app

_SERVICE_TOKEN = "discovery-service-token"
_ARTIFACT_BODY = "SECRET-ARTIFACT-BODY-8f21c9"
_DIFF_BODY = "SECRET-EDIT-DIFF-3a7be1"
_METADATA_BODY = "SECRET-METADATA-VALUE-19dd73"
_PLAN_BODY = "SECRET-PLAN-PROSE-64c1af"


def _secured(session_factory, checkpointer, aggregator: EventAggregator):
    """Build the real gateway fixture with its production bearer armed."""
    app, agg, worker, cp = make_app(session_factory, checkpointer, aggregator)
    app.state.v1_service_token = _SERVICE_TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app, agg, worker, cp


async def _seed_running_run(session_factory) -> str:
    from ...database.thread_repository import create_thread

    async with session_factory() as session:
        thread = await create_thread(session, status=ThreadStatus.RUNNING, title="run")
        await session.commit()
        return thread.id


async def _await_subscriber(agg: EventAggregator) -> None:
    for _ in range(200):
        if agg.subscriber_count() > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("stream subscriber never registered")


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_stream_excludes_artifact_body_keeps_identity(
    session_factory, checkpointer
) -> None:
    """S27/S99: an artifact body cannot cross the authenticated edge; identity does."""
    app, agg, _worker, _cp = _secured(session_factory, checkpointer, EventAggregator())
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200, resp
        lines = resp.aiter_lines()
        await _await_subscriber(agg)

        agg.relay_payload(
            run_id,
            {
                "type": "artifact_update",
                "event_type": "artifact_update",
                "thread_id": run_id,
                "artifact_id": "art-1",
                "filename": "report.md",
                "content": _ARTIFACT_BODY,
                "append": False,
                "last_chunk": True,
            },
        )

        frame, raw_block = await read_frame(
            lines, wanted="artifact_update", timeout=5.0
        )

    # Forbidden body absent (parsed and in the encoded bytes)...
    assert "content" not in frame
    assert _ARTIFACT_BODY not in raw_block
    # ...while the permitted identity is present, so an empty frame cannot pass.
    assert frame["artifact_id"] == "art-1"
    assert frame["filename"] == "report.md"


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_stream_excludes_edit_diff_keeps_tool_metadata(
    session_factory, checkpointer
) -> None:
    """S27/S99: an edit diff cannot cross; the tool-call metadata does."""
    app, agg, _worker, _cp = _secured(session_factory, checkpointer, EventAggregator())
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        lines = resp.aiter_lines()
        await _await_subscriber(agg)

        agg.relay_payload(
            run_id,
            {
                "type": "tool_call_update",
                "event_type": "tool_call_update",
                "thread_id": run_id,
                "tool_call_id": "call-1",
                "title": "Edit report.md",
                "kind": "edit",
                "status": "completed",
                "content": [
                    {
                        "content_type": "diff",
                        "path": "report.md",
                        "old_text": "old",
                        "new_text": _DIFF_BODY,
                    }
                ],
            },
        )

        frame, raw_block = await read_frame(
            lines, wanted="tool_call_update", timeout=5.0
        )

    assert "content" not in frame
    assert _DIFF_BODY not in raw_block
    assert frame["tool_call_id"] == "call-1"
    assert frame["title"] == "Edit report.md"
    assert frame["status"] == "completed"


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_stream_bounds_the_token_delta(
    session_factory, checkpointer
) -> None:
    """S159: a message frame's token content is bounded, not relayed whole."""
    app, agg, _worker, _cp = _secured(session_factory, checkpointer, EventAggregator())
    run_id = await _seed_running_run(session_factory)
    oversized = "T" * (MAX_PROGRESS_CONTENT_CHARS + 5000)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        lines = resp.aiter_lines()
        await _await_subscriber(agg)

        agg.relay_payload(
            run_id,
            {
                "type": "message_chunk",
                "event_type": "message_chunk",
                "thread_id": run_id,
                "agent_id": "worker",
                "content": oversized,
                "message_id": "m-1",
            },
        )

        frame, _raw = await read_frame(lines, wanted="message_chunk", timeout=5.0)

    # The permitted token stream is present but bounded to the per-frame cap.
    assert isinstance(frame["content"], str)
    assert len(frame["content"]) == MAX_PROGRESS_CONTENT_CHARS
    assert len(frame["content"]) < len(oversized)
    assert frame["message_id"] == "m-1"


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_stream_keeps_the_consumer_read_lifecycle_fields(
    session_factory, checkpointer
) -> None:
    """The catalog flip must not silence what the consumer actually renders.

    ``agent_status.state`` drives the live activity indicator,
    ``team_status.agents[].agent_id``/``state`` drive roster liveness, and
    ``error.message`` is the rendered fault reason. All three survive today only
    because their types are now enumerated - before the catalog closed they rode
    the default-allow path. Each is relayed through the real aggregator and read
    back off a real socket.
    """
    app, agg, _worker, _cp = _secured(session_factory, checkpointer, EventAggregator())
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200, resp
        lines = resp.aiter_lines()
        await _await_subscriber(agg)

        agg.relay_payload(
            run_id,
            {
                "type": "agent_status",
                "event_type": "agent_status",
                "thread_id": run_id,
                "node_name": "synthesis",
                "state": "working",
                "detail": "drafting",
                "metadata": {"leaked": _METADATA_BODY},
            },
        )
        status_frame, status_raw = await read_frame(
            lines, wanted="agent_status", timeout=5.0
        )

        agg.relay_payload(
            run_id,
            {
                "type": "team_status",
                "event_type": "team_status",
                "thread_id": run_id,
                "active_thread_ids": [run_id],
                "agents": [
                    {
                        "agent_id": "researcher_00",
                        "state": "working",
                        "node_name": "research_dispatch",
                        "raw_provider_payload": _METADATA_BODY,
                    }
                ],
            },
        )
        team_frame, team_raw = await read_frame(
            lines, wanted="team_status", timeout=5.0
        )

        agg.relay_payload(
            run_id,
            {
                "type": "error",
                "event_type": "error",
                "thread_id": run_id,
                "code": "worker_failed",
                "message": "provider returned 502",
                "recoverable": True,
            },
        )
        error_frame, _error_raw = await read_frame(lines, wanted="error", timeout=5.0)

    assert status_frame["state"] == "working"
    assert status_frame["node_name"] == "synthesis"
    assert "metadata" not in status_frame
    assert _METADATA_BODY not in status_raw

    assert team_frame["agents"][0]["agent_id"] == "researcher_00"
    assert team_frame["agents"][0]["state"] == "working"
    assert team_frame["active_thread_ids"] == [run_id]
    assert _METADATA_BODY not in team_raw

    assert error_frame["message"] == "provider returned 502"
    assert error_frame["code"] == "worker_failed"


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_stream_degrades_an_uncatalogued_frame(
    session_factory, checkpointer
) -> None:
    """A type nobody enumerated crosses as identity keys only, not verbatim.

    This inverts the pre-catalog edge behaviour. The type NAME survives, so a
    consumer classifying frames by name still routes it; its payload does not.
    """
    app, agg, _worker, _cp = _secured(session_factory, checkpointer, EventAggregator())
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        lines = resp.aiter_lines()
        await _await_subscriber(agg)

        agg.relay_payload(
            run_id,
            {
                "type": "some_future_event",
                "event_type": "some_future_event",
                "thread_id": run_id,
                "agent_id": "worker",
                "prompt": _ARTIFACT_BODY,
                "metadata": {"leaked": _METADATA_BODY},
            },
        )

        frame, raw_block = await read_frame(
            lines, wanted="some_future_event", timeout=5.0
        )

    assert _ARTIFACT_BODY not in raw_block
    assert _METADATA_BODY not in raw_block
    # The identity keys - and critically the type name - still cross.
    assert frame["type"] == "some_future_event"
    assert frame["thread_id"] == run_id
    assert frame["agent_id"] == "worker"


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_stream_drops_plan_prose_and_keeps_classification(
    session_factory, checkpointer
) -> None:
    """Plan entries are rebuilt item by item; the model-authored text stays home."""
    app, agg, _worker, _cp = _secured(session_factory, checkpointer, EventAggregator())
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        lines = resp.aiter_lines()
        await _await_subscriber(agg)

        agg.relay_payload(
            run_id,
            {
                "type": "plan_update",
                "event_type": "plan_update",
                "thread_id": run_id,
                "entries": [
                    {
                        "content": _PLAN_BODY,
                        "status": "in_progress",
                        "priority": "high",
                    }
                ],
            },
        )

        frame, raw_block = await read_frame(lines, wanted="plan_update", timeout=5.0)

    assert _PLAN_BODY not in raw_block
    assert frame["entries"] == [{"status": "in_progress", "priority": "high"}]


@pytest.mark.asyncio(loop_scope="function")
async def test_global_stream_quota_refuses_an_authenticated_caller_at_capacity(
    session_factory, checkpointer
) -> None:
    """S160 (global): the connection cap holds even behind a valid bearer."""
    limit = settings.max_stream_connections
    assert limit > 0, "the global stream limit must be enabled for this proof"

    aggregator = EventAggregator()
    for index in range(limit):
        aggregator.add_subscriber(f"prefill-{index}")

    app, _agg, _worker, _cp = _secured(session_factory, checkpointer, aggregator)
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
    ):
        refused = await client.get(f"/v1/runs/{run_id}/stream")

    assert refused.status_code == 503, refused.text
    assert refused.headers.get("Retry-After") == "5"


@pytest.mark.asyncio(loop_scope="function")
async def test_global_stream_quota_admits_the_authenticated_caller_below_capacity(
    session_factory, checkpointer
) -> None:
    """S160 (global): the cap is the discriminator, not the bearer.

    One slot below capacity the same authenticated request opens, proving the
    refusal above is the connection limit rather than an auth artefact.
    """
    limit = settings.max_stream_connections
    aggregator = EventAggregator()
    for index in range(limit - 1):
        aggregator.add_subscriber(f"prefill-{index}")

    app, agg, _worker, _cp = _secured(session_factory, checkpointer, aggregator)
    run_id = await _seed_running_run(session_factory)

    async with (
        _live_server(app) as base,
        httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
        ) as client,
        client.stream("GET", f"/v1/runs/{run_id}/stream") as resp,
    ):
        assert resp.status_code == 200
        await _await_subscriber(agg)
        assert agg.subscriber_count() == limit
