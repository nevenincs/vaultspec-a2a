"""Live tests for the machine-global service discovery contract.

Real filesystem, real process-liveness, and a real ``/health`` server on a real
socket — no mocks. Covers the four things this contract demands: freshness
classification, stale-pid (Crashed) detection, single-resident semantics, and
health-while-degraded still counting as a live resident.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import TYPE_CHECKING

import httpx
import uvicorn
from fastapi import FastAPI

if TYPE_CHECKING:
    from types import TracebackType

from ..discovery import (
    DiscoveryState,
    another_resident_is_live,
    classify_discovery,
    is_pid_alive,
    read_resident_service,
    remove_service_json_if_owned,
    service_json_path,
    write_service_json,
)


class _HealthServer:
    """A real uvicorn server exposing only ``/health`` on an ephemeral port."""

    def __init__(self, *, ready: bool = True) -> None:
        app = FastAPI()

        @app.get("/health")
        async def _health() -> dict[str, object]:
            return {"status": "ok", "ready": ready, "pid": os.getpid()}

        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.port = 0

    def __enter__(self) -> _HealthServer:
        self._thread.start()
        for _ in range(500):
            if self._server.started and self._server.servers:
                break
            time.sleep(0.01)
        if not (self._server.started and self._server.servers):
            raise RuntimeError("health server did not start")
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


def test_classifier_covers_absent_fresh_stale_malformed(tmp_path) -> None:
    path = service_json_path(tmp_path)
    assert classify_discovery(path)[0] is DiscoveryState.ABSENT

    write_service_json(path, port=8000, pid=os.getpid(), service_token="s3cr3t-abc")
    state, info = classify_discovery(path)
    assert state is DiscoveryState.FRESH
    assert info is not None and info.port == 8000 and info.pid == os.getpid()
    # The token is redacted from repr but preserved on disk for the engine.
    assert "s3cr3t-abc" not in repr(info)
    assert json.loads(path.read_text())["service_token"] == "s3cr3t-abc"

    old = int(time.time() * 1000) - 10_000_000
    write_service_json(path, port=8000, pid=os.getpid(), now_ms=old)
    assert classify_discovery(path)[0] is DiscoveryState.STALE

    path.write_text("{ not json", encoding="utf-8")
    assert classify_discovery(path)[0] is DiscoveryState.MALFORMED


def test_pid_liveness_and_ownership(tmp_path) -> None:
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(2**31 - 1) is False
    assert is_pid_alive(None) is False

    path = service_json_path(tmp_path)
    write_service_json(path, port=8000, pid=os.getpid())
    # A file owned by another pid is never reclaimed by us.
    write_service_json(path, port=8000, pid=424242)
    assert remove_service_json_if_owned(path, os.getpid()) is False
    assert path.exists()
    # Our own record is dropped on exit.
    write_service_json(path, port=8000, pid=os.getpid())
    assert remove_service_json_if_owned(path, os.getpid()) is True
    assert not path.exists()


def test_stale_pid_is_not_a_live_resident(tmp_path) -> None:
    """A fresh heartbeat with a dead pid reads as Crashed, not a live resident."""
    path = service_json_path(tmp_path)
    # Fresh heartbeat (now) but a pid that does not exist -> attach-never-own.
    write_service_json(path, port=8000, pid=2**31 - 1)
    state, _info = classify_discovery(path)
    assert state is DiscoveryState.FRESH  # heartbeat is fresh...
    assert another_resident_is_live(tmp_path) is False  # ...but the pid is dead.


def test_single_resident_true_only_when_fresh_live_and_healthy(tmp_path) -> None:
    with _HealthServer() as server:
        path = service_json_path(tmp_path)
        write_service_json(path, port=server.port, pid=os.getpid())
        # Fresh record + our (live) pid + a real answering /health = live resident.
        assert another_resident_is_live(tmp_path) is True

        state, info = read_resident_service(tmp_path)
        assert state is DiscoveryState.FRESH
        assert info is not None and info.port == server.port

    # Server stopped: the /health probe now fails, so no live resident.
    assert another_resident_is_live(tmp_path) is False


def test_health_while_degraded_still_counts_as_resident(tmp_path) -> None:
    """A degraded gateway (ready=false) is still a live resident: /health answers."""
    with _HealthServer(ready=False) as server:
        path = service_json_path(tmp_path)
        write_service_json(path, port=server.port, pid=os.getpid())
        body = httpx.get(f"http://127.0.0.1:{server.port}/health", timeout=2.0).json()
        assert body["ready"] is False
        assert another_resident_is_live(tmp_path) is True


def test_absent_file_licenses_a_start(tmp_path) -> None:
    """Only Absent means no resident — the caller may start and publish."""
    assert another_resident_is_live(tmp_path) is False
    assert read_resident_service(tmp_path)[0] is DiscoveryState.ABSENT
