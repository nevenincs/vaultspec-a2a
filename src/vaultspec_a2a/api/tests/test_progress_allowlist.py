"""Real authenticated-stream proofs for the positive progress allowlist.

The public ``/v1/runs/{run_id}/stream`` edge is a deliberate allowlist: it relays
a run's identifiers, lifecycle, tool and artifact identity, and a bounded token
stream, and it must never relay a prompt, document or artifact body, edit diff,
or raw provider payload. It is also bounded: an authenticated caller cannot open
an unbounded number of streams.

These drive the real edge over a real TCP socket behind the production discovery
bearer - no mocks, no auth bypass - relaying forbidden content into the same
aggregator the live server reads from and asserting it never crosses the encoded
boundary while the permitted fields do. Every exclusion assertion is paired with
a permitted-field assertion, so an empty or dropped frame cannot satisfy it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn

from ...control.config import settings
from ...streaming.aggregator import EventAggregator
from ...streaming.sse_frames import MAX_PROGRESS_CONTENT_CHARS
from ...thread.enums import ThreadStatus
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_SERVICE_TOKEN = "discovery-service-token"
_ARTIFACT_BODY = "SECRET-ARTIFACT-BODY-8f21c9"
_DIFF_BODY = "SECRET-EDIT-DIFF-3a7be1"


@contextlib.asynccontextmanager
async def _live_server(app) -> AsyncIterator[str]:
    """Serve *app* on an ephemeral loopback port and yield its base URL."""
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


async def _read_frame(
    lines: AsyncIterator[str], *, wanted: str, timeout: float = 5.0
) -> tuple[dict, str]:
    """Read SSE frames until one whose ``type`` matches; return it and its raw text.

    Heartbeat frames are skipped. The raw ``data:`` text is returned alongside the
    parsed payload so a caller can assert against the encoded bytes, not only the
    decoded structure.
    """

    async def _scan() -> tuple[dict, str]:
        buffer: list[str] = []
        async for raw in lines:
            line = raw.rstrip("\r")
            if line.startswith("data: "):
                buffer.append(line.removeprefix("data: "))
                continue
            if line == "" and buffer:
                raw_block = "".join(buffer)
                payload = json.loads(raw_block)
                buffer = []
                if payload.get("type") == wanted:
                    return payload, raw_block
        raise AssertionError(f"stream ended before a {wanted!r} frame")

    return await asyncio.wait_for(_scan(), timeout=timeout)


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

        frame, raw_block = await _read_frame(lines, wanted="artifact_update")

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

        frame, raw_block = await _read_frame(lines, wanted="tool_call_update")

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

        frame, _raw = await _read_frame(lines, wanted="message_chunk")

    # The permitted token stream is present but bounded to the per-frame cap.
    assert isinstance(frame["content"], str)
    assert len(frame["content"]) == MAX_PROGRESS_CONTENT_CHARS
    assert len(frame["content"]) < len(oversized)
    assert frame["message_id"] == "m-1"


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
