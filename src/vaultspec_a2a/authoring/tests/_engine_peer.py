"""A real loopback peer implementing the versioned engine proof protocol."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

from ...desktop._platform_acl import harden_credential_path
from ...testing import JsonReplyHandler, serve_handler

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

TEST_BEARER = "test-engine-bearer-0123456789abcdef0123456789abcdef"


def write_engine_record(path: Path, port: int, bearer: str = TEST_BEARER) -> None:
    """Publish this peer's identity with private filesystem permissions."""
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "producer": "vaultspec-engine",
                "port": port,
                "pid": os.getpid(),
                "started_ms": 1,
                "service_token": bearer,
                "last_heartbeat": int(time.time() * 1000),
            }
        ),
        encoding="utf-8",
    )
    harden_credential_path(path)


def health_proof(port: int, bearer: str, challenge: str) -> str:
    """Sign the peer's own listener/process identity, never caller-supplied identity."""
    message = f"vaultspec-engine:1\n{port}\n{os.getpid()}\n1\n{challenge}"
    return hmac.new(
        bearer.encode("ascii"), message.encode("ascii"), hashlib.sha256
    ).hexdigest()


def reply_health_proof(handler: BaseHTTPRequestHandler, bearer: str) -> None:
    """Reply on a real protocol peer's persistent authoring connection."""
    assert isinstance(handler.server, ThreadingHTTPServer)
    handler.send_response(200)
    handler.send_header(
        "x-vaultspec-engine-proof",
        health_proof(
            handler.server.server_port,
            bearer,
            handler.headers.get("x-vaultspec-engine-challenge", ""),
        ),
    )
    handler.send_header("x-vaultspec-engine-pid", str(os.getpid()))
    handler.send_header("x-vaultspec-engine-started-ms", "1")
    handler.send_header("Content-Length", "0")
    handler.end_headers()


@contextmanager
def engine_health_listener(bearer: str = TEST_BEARER) -> Generator[int]:
    """Run a real engine health listener that proves its lifecycle identity."""

    class _Health(JsonReplyHandler, BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            reply_health_proof(self, bearer)

    with serve_handler(_Health) as port:
        yield port
