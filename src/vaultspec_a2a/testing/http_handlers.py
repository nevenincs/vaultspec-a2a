"""A shared JSON-reply base for inline ``http.server`` test doubles.

Three ``authoring/tests/`` modules each stand up a real loopback engine
double and had each grown a byte-identical way to answer one: silence the
stdlib access log, then write a JSON body with the right ``Content-Type`` and
``Content-Length``. Routing is deliberately NOT here - which paths a double
serves, what it does with a request body, and what status it answers with are
each test's actual subject, so :meth:`do_GET`/:meth:`do_POST` stay declared on
the subclass. This class owns only the mechanical part underneath them.

A plain subclass rather than a mixin: ``BaseHTTPRequestHandler`` is not
designed for multiple inheritance (``self.send_response``/``self.wfile`` etc.
exist only once the base's own ``__init__`` has run its dispatch), so
inheriting it directly here - and having callers subclass THIS instead of the
stdlib class - keeps every method resolvable without a diamond.

A caller's own handler should list ``BaseHTTPRequestHandler`` a second time,
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

from __future__ import annotations

import http.server
import json
from typing import override

__all__ = ["JsonReplyHandler"]


class JsonReplyHandler(http.server.BaseHTTPRequestHandler):
    """Silences the access log and can answer one JSON reply; routes nothing."""

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Silence the default stderr access log."""

    def _reply(self, status: int, body: dict[str, object]) -> None:
        """Write *body* as the JSON response, with a correct Content-Length."""
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
