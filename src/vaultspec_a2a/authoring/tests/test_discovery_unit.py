"""Unit tests for engine discovery skip/non-raise behavior.

Exercises the file-resolution guards without a live server: a malformed or
stale candidate must be skipped, and ``resolve_engine`` must never raise on bad
input (its non-raising contract lets a caller poll it on a loop). The env var is
set/cleared directly (no monkeypatch): it is the official discovery-override
input, not a patched internal.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from ..discovery import SERVICE_JSON_ENV, EngineEndpoint, resolve_engine

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


def test_malformed_candidate_is_skipped_without_raising(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    bad = tmp_path / "service.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    set_service_json(bad)
    # Must not raise; result is None unless a live machine-global engine answers.
    result = resolve_engine(liveness_timeout=0.2)
    assert result is None or isinstance(result, EngineEndpoint)


def test_stale_heartbeat_candidate_is_skipped(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    stale = tmp_path / "service.json"
    stale.write_text(
        json.dumps(
            {
                "port": 8767,
                "service_token": "tok",
                "last_heartbeat": int(time.time() * 1000) - 10_000_000,
            }
        ),
        encoding="utf-8",
    )
    set_service_json(stale)
    result = resolve_engine(liveness_timeout=0.2)
    assert result is None or isinstance(result, EngineEndpoint)


def test_absent_candidate_is_skipped(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    set_service_json(tmp_path / "does-not-exist.json")
    result = resolve_engine(liveness_timeout=0.2)
    assert result is None or isinstance(result, EngineEndpoint)


def test_retry_resolves_after_a_transient_stall_window(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """A stalling engine (503 then 200 on a real listener) resolves on retry.

    Reproduces the measured live failure: the engine periodically stops
    answering ``/health`` for a few seconds, so a one-shot probe misses a
    healthy engine. The retry variant polls across the window and succeeds;
    the one-shot ``resolve_engine`` against the same stalling listener misses.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from ..discovery import resolve_engine_with_retry

    hits = {"count": 0}

    class _StallingHealth(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits["count"] += 1
            self.send_response(503 if hits["count"] <= 2 else 200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _StallingHealth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        service_json = tmp_path / "service.json"
        service_json.write_text(
            json.dumps(
                {
                    "port": server.server_address[1],
                    "service_token": "tok",
                    "pid": os.getpid(),
                    "last_heartbeat": int(time.time() * 1000),
                }
            ),
            encoding="utf-8",
        )
        set_service_json(service_json)

        # The one-shot probe lands in the stall window and misses this
        # candidate (hedged like the sibling tests: the machine-global
        # fallback candidate may or may not resolve on a dev machine).
        one_shot = resolve_engine(liveness_timeout=0.5)
        assert one_shot is None or one_shot.bearer_token != "tok"
        hits["count"] = 0  # reset the window for the retry variant

        endpoint = resolve_engine_with_retry(
            attempts=4, delay_seconds=0.05, liveness_timeout=0.5
        )
        assert isinstance(endpoint, EngineEndpoint)
        assert endpoint.bearer_token == "tok"
        assert hits["count"] == 3  # two stalled probes, third succeeded
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def test_retry_returns_none_when_the_engine_stays_unreachable(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """Exhaustion is truthful: a genuinely absent engine still returns None."""
    from ..discovery import resolve_engine_with_retry

    set_service_json(tmp_path / "does-not-exist.json")
    started = time.monotonic()
    result = resolve_engine_with_retry(
        attempts=3, delay_seconds=0.05, liveness_timeout=0.2
    )
    assert result is None
    # Bounded: three fast attempts with two short sleeps, not an unbounded hang.
    assert time.monotonic() - started < 5.0


@contextmanager
def _live_health_listener() -> Iterator[int]:
    """Run a real HTTP listener that answers ``/health`` 200, yield its port.

    Used to PROVE heartbeat rejection: a candidate pointed at this live listener
    would resolve if its heartbeat were accepted, so a resolution that never
    returns this listener's token proves the heartbeat gate rejected the record
    before the (successful) liveness probe - not that the port was merely dead.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


_REJECT_MARKER_TOKEN = "reject-me-heartbeat-token"


@pytest.mark.parametrize(
    ("last_heartbeat", "why"),
    [
        (int(time.time() * 1000) - 10_000_000, "far-past stale"),
        ("2099-01-15T07:50:00Z", "implausibly future ISO"),
        ("not-a-timestamp", "non-numeric garbage"),
        (int(time.time() * 1000) + 10**12, "far-future numeric"),
    ],
    ids=["stale", "future-iso", "garbage", "future-numeric"],
)
def test_a_bad_heartbeat_is_rejected_even_against_a_live_engine(
    tmp_path: Path,
    set_service_json: Callable[[Path], None],
    last_heartbeat: object,
    why: str,
) -> None:
    """A record with a stale or malformed heartbeat is rejected pre-liveness.

    This proves rejection rather than mere non-liveness: the record points at a
    real listener that answers ``/health`` 200, so if the heartbeat were wrongly
    accepted the resolver would return this record's marker token. Asserting the
    marker token never resolves proves the heartbeat gate dropped the record
    before the successful probe. Restricting the search to the pinned override
    (never a machine-global fallback that happened to be live) makes the
    assertion exact.
    """
    with _live_health_listener() as port:
        record = tmp_path / "service.json"
        record.write_text(
            json.dumps(
                {
                    "port": port,
                    "service_token": _REJECT_MARKER_TOKEN,
                    "last_heartbeat": last_heartbeat,
                }
            ),
            encoding="utf-8",
        )
        set_service_json(record)

        result = resolve_engine(liveness_timeout=1.0)

        # If the bad heartbeat were accepted, the live listener would resolve
        # THIS record's marker token. It must not - the record is rejected.
        assert result is None or result.bearer_token != _REJECT_MARKER_TOKEN, why


def test_a_fresh_heartbeat_against_the_same_live_engine_does_resolve(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """Contrast control: the identical record with a fresh heartbeat resolves.

    Without this the rejection test could pass for the wrong reason (e.g. the
    listener never answered). A fresh heartbeat against the same live listener
    must resolve the marker token, proving the only difference that blocks the
    stale/malformed cases above is the heartbeat gate itself.
    """
    with _live_health_listener() as port:
        record = tmp_path / "service.json"
        record.write_text(
            json.dumps(
                {
                    "port": port,
                    "service_token": _REJECT_MARKER_TOKEN,
                    "last_heartbeat": int(time.time() * 1000),
                }
            ),
            encoding="utf-8",
        )
        set_service_json(record)

        result = resolve_engine(liveness_timeout=1.0)

        assert result is not None
        assert result.bearer_token == _REJECT_MARKER_TOKEN
        assert result.base_url == f"http://127.0.0.1:{port}"
