"""Gateway-level SSE coverage for GET /threads/{thread_id}/stream.

Net-new coverage: before the src/ui deletion the SSE endpoint had
no automated exerciser at all — the React SPA was its only consumer. These tests
drive the real endpoint through a real ASGI app + a real SQLite thread row + the
real EventAggregator, asserting an actual ``text/event-stream`` frame. No mocks,
no test doubles. The /ws WebSocket tests do NOT cover this SSE surface.

The terminal-replay path is asserted directly because it is deterministic and
finite (the endpoint yields one ``thread_terminal`` frame and returns); it is
exactly the close-after-terminal behaviour the -17 merge extended. The live
streaming loop is exercised end-to-end by the mock-tape run proofs.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient

from ...database.thread_repository import create_thread, update_thread_status
from ...providers.conditions import ProviderCondition
from ...thread.enums import ThreadStatus
from .conftest import make_app


def _sse_frames(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Split a finite SSE body into its ``(event name, payload)`` pairs."""
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        name: str | None = None
        data: str | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        if name is not None and data is not None:
            frames.append((name, json.loads(data)))
    return frames


class TestStreamThreadEvents:
    """Direct coverage of the SSE relay endpoint."""

    def test_stream_unknown_thread_returns_404(
        self, session_factory, checkpointer
    ) -> None:
        """Streaming an unknown thread id is a clean 404, not a hanging stream."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/v1/runs/does-not-exist/stream")
        assert resp.status_code == 404

    def test_stream_terminal_thread_replays_terminal_frame(
        self, session_factory, checkpointer
    ) -> None:
        """A terminal thread replays a single ``thread_terminal`` SSE frame.

        The endpoint short-circuits for a terminal thread: it yields one frame
        and returns, so the response body is finite and deterministic — a real
        ``text/event-stream`` frame through the real endpoint, no doubles.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> str:
            async with session_factory() as session:
                thread = await create_thread(
                    session, status=ThreadStatus.COMPLETED, title="done"
                )
                await session.commit()
                return thread.id

        thread_id = asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get(f"/v1/runs/{thread_id}/stream")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert "event: thread_terminal" in body
        assert "data:" in body
        assert thread_id in body
        assert "completed" in body

    def test_stream_terminal_failure_replays_its_reason_and_condition(
        self, session_factory, checkpointer
    ) -> None:
        """A client attaching after a failure learns why, not just that.

        The replay is the ONLY thing a late client receives - there is no replay
        buffer, and every live frame the run emitted is gone - so a terminal that
        carried nothing but ``failed`` left the reason and the condition
        recoverable only from a second request. Both are read from the durable
        row here, written through the real status writer.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> str:
            async with session_factory() as session:
                thread = await create_thread(session, title="throttled run")
                await update_thread_status(
                    session,
                    thread.id,
                    ThreadStatus.FAILED,
                    failure_reason="RateLimitError: too many requests",
                    provider_condition=ProviderCondition.THROTTLED.value,
                )
                await session.commit()
                return thread.id

        thread_id = asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get(f"/v1/runs/{thread_id}/stream")

        assert resp.status_code == 200
        frames = _sse_frames(resp.text)
        assert [name for name, _ in frames] == ["error", "thread_terminal"], (
            "a replayed failure carries the coded frame before its terminal, "
            "in the order a live client received them"
        )

        error = frames[0][1]
        assert error["code"] == ProviderCondition.THROTTLED.value
        assert error["message"] == "RateLimitError: too many requests"
        # The run is over; nothing about it is retryable any more.
        assert error["recoverable"] is False

        terminal = frames[1][1]
        assert terminal["status"] == ThreadStatus.FAILED.value
        assert terminal["replay"] is True
        assert terminal["error_detail"] == "RateLimitError: too many requests"

    def test_stream_terminal_failure_without_a_condition_falls_back_to_the_floor(
        self, session_factory, checkpointer
    ) -> None:
        """A row written before the condition column still replays its reason.

        The reason alone is the honest report there: the run failed and the
        record says why, but nothing observed a provider condition, so the frame
        carries the vocabulary's floor rather than a member it never saw.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> str:
            async with session_factory() as session:
                thread = await create_thread(session, title="legacy failure")
                await update_thread_status(
                    session,
                    thread.id,
                    ThreadStatus.FAILED,
                    failure_reason="ValueError: bad workspace root",
                )
                await session.commit()
                return thread.id

        thread_id = asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get(f"/v1/runs/{thread_id}/stream")

        frames = _sse_frames(resp.text)
        assert [name for name, _ in frames] == ["error", "thread_terminal"]
        assert frames[0][1]["code"] == ProviderCondition.UNKNOWN.value
        assert frames[0][1]["message"] == "ValueError: bad workspace root"
        assert frames[1][1]["error_detail"] == "ValueError: bad workspace root"

    def test_stream_terminal_success_replays_no_error_frame(
        self, session_factory, checkpointer
    ) -> None:
        """A completed run must not be reported as a failure on reconnect.

        The companion to the failure cases and the reason they are guarded: a
        replay that emitted an error frame unconditionally would tell every
        reconnecting client that a finished run had failed.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed() -> str:
            async with session_factory() as session:
                thread = await create_thread(
                    session, status=ThreadStatus.COMPLETED, title="done"
                )
                await session.commit()
                return thread.id

        thread_id = asyncio.run(_seed())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get(f"/v1/runs/{thread_id}/stream")

        frames = _sse_frames(resp.text)
        assert [name for name, _ in frames] == ["thread_terminal"]
        assert frames[0][1]["status"] == ThreadStatus.COMPLETED.value
        assert "error_detail" not in frames[0][1]
