"""Gateway-level SSE coverage for GET /threads/{thread_id}/stream.

Net-new coverage (W02.P03.S09): before the src/ui deletion the SSE endpoint had
no automated exerciser at all — the React SPA was its only consumer. These tests
drive the real endpoint through a real ASGI app + a real SQLite thread row + the
real EventAggregator, asserting an actual ``text/event-stream`` frame. No mocks,
no test doubles. The /ws WebSocket tests do NOT cover this SSE surface.

The terminal-replay path is asserted directly because it is deterministic and
finite (the endpoint yields one ``thread_terminal`` frame and returns); it is
exactly the close-after-terminal behaviour the -17 merge extended. The live
streaming loop is exercised end-to-end by the mock-tape run proofs (S02/S14).
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from ...database.thread_repository import create_thread
from ...thread.enums import ThreadStatus
from .conftest import make_app


class TestStreamThreadEvents:
    """Direct coverage of the SSE relay endpoint."""

    def test_stream_unknown_thread_returns_404(
        self, session_factory, checkpointer
    ) -> None:
        """Streaming an unknown thread id is a clean 404, not a hanging stream."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/does-not-exist/stream")
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
            resp = client.get(f"/api/threads/{thread_id}/stream")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert "event: thread_terminal" in body
        assert "data:" in body
        assert thread_id in body
        assert "completed" in body
