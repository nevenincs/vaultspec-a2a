"""Prove the discovery reader parses both legacy and versioned records.

The engine resolver must keep resolving a legacy inline-token record unchanged
while a versioned, secret-free desktop record is recognised (not misread as
malformed) and skipped for engine resolution because it carries no inline
bearer. A real loopback ``/health`` server backs the resolution assertions; the
discovery override is set through its official environment variable, not a
patched internal. No mock, monkeypatch, stub, skip, or expected failure is used.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ..discovery import (
    DESKTOP_RECORD_VERSION,
    SERVICE_JSON_ENV,
    EngineEndpoint,
    parse_discovery_record,
    read_discovery_record,
    resolve_engine,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture
def set_service_json() -> Iterator[Callable[[Path], None]]:
    """Yield a setter for the discovery override; restore the prior value after."""
    previous = os.environ.get(SERVICE_JSON_ENV)

    def _set(path: Path) -> None:
        os.environ[SERVICE_JSON_ENV] = str(path)

    try:
        yield _set
    finally:
        if previous is None:
            os.environ.pop(SERVICE_JSON_ENV, None)
        else:
            os.environ[SERVICE_JSON_ENV] = previous


def _versioned_record(port: int, *, credential_reference: str) -> dict:
    return {
        "version": DESKTOP_RECORD_VERSION,
        "profile": "desktop",
        "generation": "gen-1",
        "protocol": {"min": 1, "max": 1},
        "process": {"pid": os.getpid(), "start_fingerprint": "fp"},
        "endpoint": {"host": "127.0.0.1", "port": port},
        "last_heartbeat": int(time.time() * 1000),
        "owner": "alice",
        "credential_reference": credential_reference,
    }


def test_parses_versioned_record_as_secret_free() -> None:
    """A versioned record parses with no bearer and only a credential path."""
    view = parse_discovery_record(_versioned_record(8200, credential_reference="/c/a"))
    assert view is not None
    assert view.versioned is True
    assert view.port == 8200
    assert view.bearer_token is None
    assert view.credential_reference == "/c/a"
    assert view.base_url == "http://127.0.0.1:8200"


def test_parses_legacy_record_with_inline_bearer() -> None:
    """A legacy R8 record parses with its inline machine bearer."""
    view = parse_discovery_record(
        {"port": 8201, "service_token": "tok", "last_heartbeat": 1}
    )
    assert view is not None
    assert view.versioned is False
    assert view.port == 8201
    assert view.bearer_token == "tok"


def test_record_without_port_is_fail_closed() -> None:
    """A record missing a valid integer port yields no view."""
    assert parse_discovery_record({"service_token": "tok"}) is None
    assert parse_discovery_record({"port": "not-an-int"}) is None
    assert (
        parse_discovery_record(
            {"version": DESKTOP_RECORD_VERSION, "profile": "desktop", "endpoint": {}}
        )
        is None
    )


def test_round_trip_read_of_versioned_and_legacy(tmp_path: Path) -> None:
    """Both record shapes read from disk into their expected views."""
    versioned = tmp_path / "versioned.json"
    versioned.write_text(
        json.dumps(_versioned_record(8202, credential_reference="/c/b")),
        encoding="utf-8",
    )
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps({"port": 8203, "service_token": "tok"}), encoding="utf-8"
    )

    versioned_view = read_discovery_record(versioned)
    legacy_view = read_discovery_record(legacy)
    assert versioned_view is not None and versioned_view.versioned is True
    assert legacy_view is not None and legacy_view.bearer_token == "tok"


def _serve_health() -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    class _Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def test_legacy_record_still_resolves_the_engine(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """The engine path is unchanged: a legacy record with a live health resolves."""
    server, thread, port = _serve_health()
    try:
        path = tmp_path / "service.json"
        path.write_text(
            json.dumps(
                {
                    "port": port,
                    "service_token": "tok-legacy",
                    "pid": os.getpid(),
                    "last_heartbeat": int(time.time() * 1000),
                }
            ),
            encoding="utf-8",
        )
        set_service_json(path)
        endpoint = resolve_engine(liveness_timeout=0.5)
        assert isinstance(endpoint, EngineEndpoint)
        assert endpoint.bearer_token == "tok-legacy"
        assert endpoint.base_url == f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def test_versioned_record_is_not_resolved_as_an_engine(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """A secret-free versioned record is recognised but never becomes an endpoint.

    Even with a live health server on its port, the engine resolver skips it (no
    inline bearer); any endpoint returned would be the machine-global fallback,
    never this port.
    """
    server, thread, port = _serve_health()
    try:
        path = tmp_path / "service.json"
        credential_file = tmp_path / "attach.cred"
        credential_file.write_text("secret-bearer", encoding="utf-8")
        record = _versioned_record(port, credential_reference=str(credential_file))
        path.write_text(json.dumps(record), encoding="utf-8")
        set_service_json(path)
        result = resolve_engine(liveness_timeout=0.5)
        assert result is None or result.base_url != f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
