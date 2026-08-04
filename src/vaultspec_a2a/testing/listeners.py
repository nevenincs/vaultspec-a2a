"""Real loopback listeners a test points a production probe at.

Several production paths decide something by asking whether a service answers
``/health``: engine discovery resolves a record only after a successful liveness
probe, and the worker watchdog reconciles state against the same question. To
test what those paths DO with the answer, something has to actually answer -
which is why this is a real ``http.server`` on real loopback rather than a
substitute for the probe. The code under test performs its own genuine HTTP
request; only the peer is ours.

:func:`health_listener` is the plain affirmative case, and it is the only thing
that belongs here. The interesting listeners are the negative ones - a peer that
accepts a connection and never responds, one that answers 200 with undecodable
bytes, one that stalls past a retry window - and each of those exists to prove a
specific failure is handled. They stay beside the test that owns them, because
their behaviour IS the test's subject rather than a shared fixture; folding them
in here would leave a helper whose options are a catalogue of unrelated defects.

The listener binds port zero and holds the socket, so it takes no reservation
from :mod:`vaultspec_a2a.testing.ports`. That is not an oversight and not a
double standard: a registry claim exists to stop a port being handed twice in
the window before someone binds it, and here the bind is what allocation
returns. A port handed to a CHILD that binds later still goes through the
registry.
"""

from __future__ import annotations

import contextlib
import http.server
import threading
from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["health_listener"]

_SHUTDOWN_JOIN_TIMEOUT_S = 5.0


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """Answers ``/health`` and nothing else."""

    # Not an override: BaseHTTPRequestHandler dispatches by building the method
    # name from the request verb, so this name is a contract with the base class
    # rather than a redefinition of one of its methods.
    def do_GET(self) -> None:
        """Serve 200 with an empty JSON object on ``/health``, else 404."""
        body = b"{}" if self.path == "/health" else b""
        self.send_response(200 if self.path == "/health" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    @override
    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default stderr access log."""


@contextlib.contextmanager
def health_listener() -> Iterator[int]:
    """Serve ``/health`` on a loopback port for the body, then shut down.

    Yields the port. Threaded, so a caller whose code under test opens more than
    one connection is not serialised behind its own first request, and joined on
    exit so a finished test leaves no thread still bound to the port a later
    test may be handed.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
