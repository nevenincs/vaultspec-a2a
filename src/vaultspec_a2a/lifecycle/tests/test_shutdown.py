"""Live-socket proof of the shared Uvicorn shutdown deadline."""

from __future__ import annotations

import asyncio
import functools
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from ...testing import loopback_uvicorn, uvicorn_started
from ..shutdown import ShutdownDeadline, ShutdownServer, build_shutdown_server


@pytest.mark.asyncio(loop_scope="function")
async def test_parked_sse_is_cancelled_inside_the_server_shutdown_clock() -> None:
    stream_open = asyncio.Event()
    observed_remaining: list[float] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        deadline = app.state.shutdown_deadline
        assert isinstance(deadline, ShutdownDeadline)
        observed_remaining.append(deadline.remaining())

    app = FastAPI(lifespan=lifespan)

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def body():
            stream_open.set()
            yield b"event: ready\ndata: {}\n\n"
            await asyncio.Event().wait()

        return StreamingResponse(body(), media_type="text/event-stream")

    server = loopback_uvicorn(
        app,
        log_level="error",
        timeout_graceful_shutdown=1,
        server_factory=functools.partial(ShutdownServer, app=app, total_seconds=3.0),
    )
    serving = asyncio.create_task(server.serve())
    try:
        base = await uvicorn_started(server, serving)
        async with (
            httpx.AsyncClient(timeout=5.0) as client,
            client.stream("GET", f"{base}/stream") as response,
        ):
            assert response.status_code == 200
            iterator = response.aiter_bytes()
            first = await anext(iterator)
            assert b"event: ready" in first
            assert stream_open.is_set()

            started = asyncio.get_running_loop().time()
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=3.5)
            elapsed = asyncio.get_running_loop().time() - started
    finally:
        server.should_exit = True
        if not serving.done():
            await asyncio.wait_for(serving, timeout=3.5)

    assert elapsed < 3.5
    assert observed_remaining, "lifespan never observed the server shutdown clock"
    assert observed_remaining[0] < 2.5, (
        "lifespan received a reset deadline after the parked stream grace elapsed"
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_built_server_stops_when_the_app_requests_its_owner_to() -> None:
    app = FastAPI()
    server = build_shutdown_server(app, host="127.0.0.1", port=0)
    serving = asyncio.create_task(server.serve())
    try:
        await uvicorn_started(server, serving)
        assert not server.should_exit

        app.state.request_server_shutdown()
        await asyncio.wait_for(serving, timeout=3.5)
    finally:
        server.should_exit = True
        if not serving.done():
            await asyncio.wait_for(serving, timeout=3.5)

    assert server.should_exit
    assert isinstance(app.state.shutdown_deadline, ShutdownDeadline)
