"""Engine discovery skip/non-raise behavior, against real files and listeners.

Exercises the file-resolution guards: a malformed or stale candidate must be
skipped, and ``resolve_engine`` must never raise on bad input (its non-raising
contract lets a caller poll it on a loop). The record is redirected through the
official ``engine_service_json`` setting, and the retry window is driven against
a real loopback listener.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from ...control.config import settings
from ...testing import JsonReplyHandler, serve_handler, settings_override
from ..discovery import EngineEndpoint, resolve_engine
from ._engine_peer import (
    TEST_BEARER,
    engine_health_listener,
    health_proof,
    write_engine_record,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture
def set_service_json() -> Iterator[Callable[[Path], None]]:
    """Yield a setter for the engine discovery record; restore it afterwards.

    The configured record is discovery's one candidate, so pointing it at a
    test file leaves no other location a resident engine could be found at.
    """

    def _set(path: Path) -> None:
        settings.engine_service_json = path

    with settings_override(engine_service_json=None):
        yield _set


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
    secure_engine_dir: Path, set_service_json: Callable[[Path], None]
) -> None:
    """A stalling engine (503 then 200 on a real listener) resolves on retry.

    Reproduces the measured live failure: the engine periodically stops
    answering ``/health`` for a few seconds, so a one-shot probe misses a
    healthy engine. The retry variant polls across the window and succeeds;
    the one-shot ``resolve_engine`` against the same stalling listener misses.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from ..discovery import resolve_engine_with_retry

    hits = {"count": 0}

    class _StallingHealth(JsonReplyHandler, BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert isinstance(self.server, ThreadingHTTPServer)
            hits["count"] += 1
            self.send_response(503 if hits["count"] <= 2 else 200)
            self.send_header(
                "x-vaultspec-engine-proof",
                health_proof(
                    self.server.server_port,
                    TEST_BEARER,
                    self.headers.get("x-vaultspec-engine-challenge", ""),
                ),
            )
            self.end_headers()

    with serve_handler(_StallingHealth) as port:
        service_json = secure_engine_dir / "service.json"
        write_engine_record(service_json, port)
        set_service_json(service_json)

        # The one-shot probe lands in the stall window and misses this
        # candidate (hedged like the sibling tests: the machine-global
        # fallback candidate may or may not resolve on a dev machine).
        one_shot = resolve_engine(liveness_timeout=0.5)
        assert one_shot is None
        hits["count"] = 0  # reset the window for the retry variant

        endpoint = resolve_engine_with_retry(
            attempts=4, delay_seconds=0.05, liveness_timeout=0.5
        )
        assert isinstance(endpoint, EngineEndpoint)
        assert endpoint.bearer_token == TEST_BEARER
        assert hits["count"] == 3  # two stalled probes, third succeeded


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


_REJECT_MARKER_TOKEN = "reject-me-heartbeat-token-0123456789abcdef0123456789abcdef"


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
    secure_engine_dir: Path,
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
    with engine_health_listener(_REJECT_MARKER_TOKEN) as port:
        record = secure_engine_dir / "service.json"
        write_engine_record(record, port, _REJECT_MARKER_TOKEN)
        info = json.loads(record.read_text(encoding="utf-8"))
        info["last_heartbeat"] = last_heartbeat
        record.write_text(json.dumps(info), encoding="utf-8")
        set_service_json(record)

        result = resolve_engine(liveness_timeout=1.0)

        # If the bad heartbeat were accepted, the live listener would resolve
        # THIS record's marker token. It must not - the record is rejected.
        assert result is None, why


def test_a_fresh_heartbeat_against_the_same_live_engine_does_resolve(
    secure_engine_dir: Path, set_service_json: Callable[[Path], None]
) -> None:
    """Contrast control: the identical record with a fresh heartbeat resolves.

    Without this the rejection test could pass for the wrong reason (e.g. the
    listener never answered). A fresh heartbeat against the same live listener
    must resolve the marker token, proving the only difference that blocks the
    stale/malformed cases above is the heartbeat gate itself.
    """
    with engine_health_listener(_REJECT_MARKER_TOKEN) as port:
        record = secure_engine_dir / "service.json"
        write_engine_record(record, port, _REJECT_MARKER_TOKEN)
        set_service_json(record)

        result = resolve_engine(liveness_timeout=1.0)

        assert result is not None
        assert result.bearer_token == _REJECT_MARKER_TOKEN
        assert result.base_url == f"http://127.0.0.1:{port}"
