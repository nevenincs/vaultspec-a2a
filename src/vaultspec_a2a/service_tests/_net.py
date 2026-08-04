"""Bare TCP connectivity probes shared by the service-tier certification tests."""

from __future__ import annotations

import socket
from urllib.parse import urlparse

__all__ = ["tape_server_listening"]


def tape_server_listening(base: str) -> bool:
    """Whether something is actually accepting connections at *base*."""
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        return probe.connect_ex((host, port)) == 0
