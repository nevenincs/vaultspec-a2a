"""Bare TCP connectivity probes shared by the service-tier certification tests."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

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
    """Whether something is actually accepting connections at *base*."""
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        return probe.connect_ex((host, port)) == 0
