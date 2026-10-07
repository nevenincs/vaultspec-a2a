"""Bare TCP connectivity probes shared by the service-tier certification tests."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from ..utils._process_tree import port_has_listener

__all__ = ["TAPE_SERVER_ENV", "tape_server_base", "tape_server_listening"]

# The scripted backend the mock provider proxies to. The compose service publishes
# it on this loopback port; an environment that already runs one points at it with
# the same variable the production provider reads.
_TAPE_SERVER_DEFAULT = "http://127.0.0.1:8100"
TAPE_SERVER_ENV = "VAULTSPEC_A2A_MOCK_API_BASE"


def tape_server_base() -> str:
    """The scripted backend's base URL, overridable by the production variable."""
    return (os.environ.get(TAPE_SERVER_ENV) or "").strip() or _TAPE_SERVER_DEFAULT


def tape_server_listening(base: str) -> bool:
    """Whether something is accepting connections on *base*'s loopback port.

    The scripted backend is a loopback service, so only the port is probed.
    """
    parsed = urlparse(base)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return port_has_listener(port, timeout=2.0)
