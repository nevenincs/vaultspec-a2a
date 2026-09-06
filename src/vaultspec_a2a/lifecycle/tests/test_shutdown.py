"""Live-socket proof of the shared Uvicorn shutdown deadline."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from ..shutdown import ShutdownDeadline, ShutdownServer


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

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]

    config = uvicorn.Config(
        app,
        log_level="error",
        lifespan="on",
        timeout_graceful_shutdown=1,
    )
    server = ShutdownServer(config, app=app, total_seconds=3.0)
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        async with (
            httpx.AsyncClient(timeout=5.0) as client,
            client.stream(
                "GET", f"http://127.0.0.1:{port}/stream"
            ) as response,
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
        listener.close()

    assert elapsed < 3.5
    assert observed_remaining, "lifespan never observed the server shutdown clock"
    assert observed_remaining[0] < 2.5, (
        "lifespan received a reset deadline after the parked stream grace elapsed"
    )
