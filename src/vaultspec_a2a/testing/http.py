"""Real loopback listeners a test points the code under test at.

Two kinds of peer stand on a real loopback socket here, and each has one
lifecycle:

- an ASGI application served by a real uvicorn server, through
  :func:`serve_on_loopback` (for a test running an event loop) or
  :func:`serve_on_loopback_in_thread` (for a synchronous caller, or a peer that
  must keep answering while the test blocks). A real TCP socket rather than
  ``ASGITransport``: an SSE consumer must read frames while the producer is
  still emitting, and the in-memory transport buffers a whole response before
  returning one.
- a stdlib ``http.server`` handler, through :func:`serve_handler`, for a peer
  whose behaviour is a handful of hand-written replies - an engine double, a
  health listener, a provider endpoint replaying a scripted turn.

The code under test performs its own genuine HTTP request against either; only
the peer is ours. Routing is deliberately NOT shared: which paths a peer serves,
what it does with a request body, and what status it answers with are each
test's actual subject, so a handler's ``do_GET``/``do_POST`` stay declared on the
test's own subclass of :class:`JsonReplyHandler`, which owns only the mechanical
part underneath them. :func:`health_listener` is the one affirmative peer shared
as-is; the interesting peers are negative ones - a listener that stalls, one that
answers with the wrong proof - whose behaviour IS the test's subject.

Every listener binds port zero and holds the socket, so none takes a reservation
from :mod:`vaultspec_a2a.testing.ports`. A registry claim exists to stop a port
being handed twice in the window before someone binds it, and here the bind is
what allocation returns. A port handed to a CHILD that binds later still goes
through the registry.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import threading
import time
from typing import TYPE_CHECKING, Literal, override

import uvicorn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

__all__ = [
    "JsonReplyHandler",
    "health_listener",
    "loopback_uvicorn",
    "serve_handler",
    "serve_on_loopback",
    "serve_on_loopback_in_thread",
    "uvicorn_started",
]

type AsgiApp = Callable[..., Awaitable[None]]
type Lifespan = Literal["auto", "on", "off"]

# Generous rather than tuned: a lifespan that seats a real database can take
# seconds on a loaded host, and readiness returns the moment the socket binds.
_START_BUDGET_S = 10.0
_SHUTDOWN_JOIN_TIMEOUT_S = 5.0


class JsonReplyHandler(http.server.BaseHTTPRequestHandler):
    """Silences the access log and can answer one reply; routes nothing.

    A plain subclass rather than a mixin: ``BaseHTTPRequestHandler`` is not
    designed for multiple inheritance (``self.send_response``/``self.wfile`` etc.
    exist only once the base's own ``__init__`` has run its dispatch), so
    inheriting it directly here - and having callers subclass THIS instead of the
    stdlib class - keeps every method resolvable without a diamond.

    A caller's own handler lists ``BaseHTTPRequestHandler`` a second time,
    redundantly, alongside this class::

        class _Handler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None: ...

    The redundancy is deliberate, not a slip to "clean up": pep8-naming only
    recognises ``do_GET``/``do_POST`` as the stdlib dispatch convention (exempt
    from snake_case) when that literal name appears in the handler's own direct
    bases, and it does not resolve the exemption through an intermediate,
    project-local class. The MRO is unaffected either way, since this class
    already extends the stdlib one.
    """

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Silence the default stderr access log."""

    def _reply(self, status: int, body: object) -> None:
        """Write *body* as the JSON response, with a correct Content-Length."""
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _reply_empty(self, status: int) -> None:
        """Answer *status* with no body."""
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _HealthHandler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
    """Answers ``/health`` and nothing else."""

    def do_GET(self) -> None:
        """Serve 200 with an empty JSON object on ``/health``, else 404."""
        if self.path == "/health":
            self._reply(200, {})
        else:
            self._reply_empty(404)


@contextlib.contextmanager
def serve_handler(
    handler: type[http.server.BaseHTTPRequestHandler], *, port: int = 0
) -> Generator[int]:
    """Serve *handler* on a loopback port for the body, then shut down.

    Yields the bound port. *port* pins it, for a test that must take over an
    address another listener just vacated; otherwise the bind picks one.
    Threaded, so a caller whose code under test opens more than one connection
    is not serialised behind its own first request, and joined on exit so a
    finished test leaves no thread still bound to the port a later test may be
    handed.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)


@contextlib.contextmanager
def health_listener() -> Generator[int]:
    """Serve ``/health`` on a loopback port for the body, then shut down."""
    with serve_handler(_HealthHandler) as port:
        yield port


def loopback_uvicorn(
    app: AsgiApp, *, lifespan: Lifespan = "on", log_level: str = "warning"
) -> uvicorn.Server:
    """A uvicorn server for *app* on an ephemeral loopback port, not yet serving.

    For a test whose subject is the server's own lifecycle - who owns its exit,
    how it drains - and so has to hold the server and its serving task itself.
    Every other caller wants :func:`serve_on_loopback`.
    """
    return uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level=log_level, lifespan=lifespan
        )
    )


def _base_url(server: uvicorn.Server) -> str:
    port = server.servers[0].sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}"


async def uvicorn_started(server: uvicorn.Server, serving: asyncio.Task[None]) -> str:
    """Wait until *server* has bound, returning its base URL.

    *serving* is the task running ``server.serve()``: a server that exits before
    it binds re-raises its own failure here rather than leaving the caller to
    wait out the budget for a socket that will never exist.
    """
    deadline = time.monotonic() + _START_BUDGET_S
    while not (server.started and server.servers):
        if serving.done():
            await serving
            raise AssertionError("uvicorn exited before it started")
        if time.monotonic() > deadline:
            raise AssertionError("uvicorn did not start")
        await asyncio.sleep(0.01)
    return _base_url(server)


@contextlib.asynccontextmanager
async def serve_on_loopback(
    app: AsgiApp, *, lifespan: Lifespan = "on", log_level: str = "warning"
) -> AsyncGenerator[str]:
    """Serve *app* on an ephemeral loopback port and yield its base URL.

    The server runs on the caller's own event loop and is asked to exit when the
    body ends; a server that does not finish within the shutdown budget is left
    to the loop's own teardown rather than failing a test that already passed.
    """
    server = loopback_uvicorn(app, lifespan=lifespan, log_level=log_level)
    serving = asyncio.create_task(server.serve())
    try:
        yield await uvicorn_started(server, serving)
    finally:
        server.should_exit = True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(serving, timeout=_SHUTDOWN_JOIN_TIMEOUT_S)


@contextlib.contextmanager
def serve_on_loopback_in_thread(
    app: AsgiApp, *, lifespan: Lifespan = "on", log_level: str = "warning"
) -> Generator[str]:
    """Serve *app* from a daemon thread with its own loop and yield its base URL.

    For a synchronous caller, or a peer that must keep answering while the test
    blocks - a child process connecting back while the test waits on it.
    """
    server = loopback_uvicorn(app, lifespan=lifespan, log_level=log_level)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + _START_BUDGET_S
        while not (server.started and server.servers):
            if not thread.is_alive():
                raise AssertionError("uvicorn exited before it started")
            if time.monotonic() > deadline:
                raise AssertionError("uvicorn did not start")
            time.sleep(0.01)
        yield _base_url(server)
    finally:
        server.should_exit = True
        thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
