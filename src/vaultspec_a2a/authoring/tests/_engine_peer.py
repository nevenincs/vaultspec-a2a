"""A real loopback peer implementing the versioned engine proof protocol."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from ...desktop._platform_acl import harden_credential_path
from ...testing import JsonReplyHandler, serve_handler
from .._engine_trust import (
    CHALLENGE_HEADER,
    ENGINE_PRODUCER,
    ENGINE_RECORD_VERSION,
    PID_HEADER,
    PROOF_HEADER,
    STARTED_MS_HEADER,
    TrustedEngineRecord,
    proof_digest,
)

if TYPE_CHECKING:
    from collections.abc import Generator

TEST_BEARER = "test-engine-bearer-0123456789abcdef0123456789abcdef"
_STARTED_MS = 1


@contextmanager
def private_engine_dir() -> Generator[Path]:
    """Hold trusted producer state outside any repository under a private ACL.

    A discovery record is read only from an owner-restricted directory that no
    repository content controls, so a record a test wants resolved cannot live
    under the session seat: that seat is inside this checkout. Every consumer of
    the record shares this one seat so the provenance rule is satisfied the same
    way wherever it is exercised.
    """
    # storage-anchor-ok: trusted producer fixtures must be outside any repository.
    with TemporaryDirectory(  # storage-anchor-ok
        prefix="vaultspec-engine-security-"
    ) as directory:
        path = Path(directory)
        harden_credential_path(path)
        yield path


def write_engine_record(path: Path, port: int, bearer: str = TEST_BEARER) -> None:
    """Publish this peer's identity with private filesystem permissions."""
    path.write_text(
        json.dumps(
            {
                "version": ENGINE_RECORD_VERSION,
                "producer": ENGINE_PRODUCER,
                "port": port,
                "pid": os.getpid(),
                "started_ms": _STARTED_MS,
                "service_token": bearer,
                "last_heartbeat": int(time.time() * 1000),
            }
        ),
        encoding="utf-8",
    )
    harden_credential_path(path)


def health_proof(port: int, bearer: str, challenge: str) -> str:
    """Sign the peer's own listener/process identity, never caller-supplied identity."""
    record = TrustedEngineRecord(port, os.getpid(), _STARTED_MS, bearer)
    return proof_digest(bearer, record.proof_message(challenge))


def reply_health_proof(handler: BaseHTTPRequestHandler, bearer: str) -> None:
    """Reply on a real protocol peer's persistent authoring connection."""
    assert isinstance(handler.server, ThreadingHTTPServer)
    handler.send_response(200)
    handler.send_header(
        PROOF_HEADER,
        health_proof(
            handler.server.server_port,
            bearer,
            handler.headers.get(CHALLENGE_HEADER, ""),
        ),
    )
    handler.send_header(PID_HEADER, str(os.getpid()))
    handler.send_header(STARTED_MS_HEADER, str(_STARTED_MS))
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
