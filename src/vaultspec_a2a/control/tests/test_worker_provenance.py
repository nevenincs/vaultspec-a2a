"""Public spawn-path proof for worker provenance and held-port safety.

Real loopback HTTP servers, no mocks. A worker's health response is useful only
when its declaration proves that it belongs to this gateway. These tests drive
the public health probe and lazy spawner, rather than reaching into their
classification and eviction helpers.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import textwrap
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypedDict, override

import pytest

from ...control.config import INTERNAL_TOKEN_ENV, settings
from ...control.worker_management import (
    LazyWorkerSpawner,
    WorkerHealthProbe,
    probe_worker_health,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class _ShutdownObservation(TypedDict):
    called: bool
    authorization: str | None


def _make_handler(
    body: dict[str, object] | None,
    shutdown_log: _ShutdownObservation,
) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health" or body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            if self.path != "/admin/shutdown":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            shutdown_log["called"] = True
            shutdown_log["authorization"] = self.headers.get("Authorization")
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()

        @override
        def log_message(self, format: str, *args: object) -> None:
            """Silence the default access log."""

    return _Handler


@contextmanager
def _worker_like(
    body: dict[str, object] | None,
) -> Generator[tuple[str, int, _ShutdownObservation]]:
    shutdown_log: _ShutdownObservation = {"called": False, "authorization": None}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), _make_handler(body, shutdown_log)
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", port, shutdown_log
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_probe_worker_health_returns_body_with_gateway_target() -> None:
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:8000",
    }
    with _worker_like(body) as (url, _port, _log):
        probe = await probe_worker_health(url)
    assert probe == WorkerHealthProbe(healthy=True, body=body)


@pytest.mark.asyncio
async def test_probe_worker_health_reports_unreachable_as_unhealthy_without_body() -> (
    None
):
    assert await probe_worker_health("http://127.0.0.1:9") == WorkerHealthProbe(
        healthy=False,
        body=None,
    )


@pytest.mark.asyncio
async def test_ensure_worker_attaches_to_a_same_gateway_worker() -> None:
    """The public non-spawning path adopts the correctly targeted incumbent."""
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": settings.gateway_url,
    }
    with _worker_like(body) as (url, port, _log):
        spawner = LazyWorkerSpawner(worker_url=url, worker_port=port, auto_spawn=False)
        await spawner.ensure_worker()
    assert spawner.spawned is True
    assert spawner.process is None


@pytest.mark.asyncio
async def test_ensure_worker_adopts_legacy_missing_or_blank_target() -> None:
    """The public attach path keeps both legacy target forms adoptable."""
    legacy_without_target: dict[str, object] = {"status": "ok", "service": "worker"}
    legacy_with_blank_target: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "",
    }
    for body in (legacy_without_target, legacy_with_blank_target):
        with _worker_like(body) as (url, port, _log):
            spawner = LazyWorkerSpawner(
                worker_url=url,
                worker_port=port,
                auto_spawn=False,
            )
            await spawner.ensure_worker()
        assert spawner.spawned is True
        assert spawner.process is None


@pytest.mark.asyncio
async def test_ensure_worker_refuses_a_foreign_worker_without_auto_spawn() -> None:
    """A public attach request never adopts a live foreign incumbent."""
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _worker_like(body) as (url, port, _log):
        spawner = LazyWorkerSpawner(worker_url=url, worker_port=port, auto_spawn=False)
        await spawner.ensure_worker()
    assert spawner.spawned is False
    assert spawner.process is None


@pytest.mark.asyncio
async def test_ensure_worker_refuses_an_unreachable_worker_without_auto_spawn() -> None:
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9",
        worker_port=9,
        auto_spawn=False,
    )
    await spawner.ensure_worker()
    assert spawner.spawned is False
    assert spawner.process is None


@pytest.mark.asyncio
async def test_auto_spawn_refuses_retained_foreign_worker() -> None:
    """A failed foreign-worker eviction stays unpaired instead of competing.

    The loopback worker accepts the gateway's normal authenticated shutdown
    request but deliberately retains the port, reproducing the no-competitor
    boundary through the public auto-spawn request.
    """
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _worker_like(body) as (url, port, log):
        spawner = LazyWorkerSpawner(worker_url=url, worker_port=port, auto_spawn=True)
        await spawner.ensure_worker()
        still_healthy = await probe_worker_health(url)
    expected_authorization = (
        None if settings.internal_token is None else f"Bearer {settings.internal_token}"
    )
    assert log == {"called": True, "authorization": expected_authorization}
    assert still_healthy == WorkerHealthProbe(healthy=True, body=body)
    assert spawner.spawned is False
    assert spawner.process is None


@pytest.mark.parametrize(
    ("internal_token", "expected_authorization"),
    [(None, None), ("evict-secret", "Bearer evict-secret")],
)
def test_subprocess_auto_spawn_sends_configured_shutdown_authorization(
    tmp_path: Path,
    internal_token: str | None,
    expected_authorization: str | None,
) -> None:
    """A fresh gateway process presents precisely its configured IPC credential.

    The parent owns the foreign worker's real loopback port. The child only uses
    public worker-management APIs, attempts automatic foreign-worker eviction,
    and proves that the retained foreign process was not adopted.
    """
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _worker_like(body) as (url, port, observer):
        child_environment = os.environ.copy()
        child_environment.pop(INTERNAL_TOKEN_ENV, None)
        child_environment["VAULTSPEC_ENVIRONMENT"] = "development"
        if internal_token is not None:
            child_environment[INTERNAL_TOKEN_ENV] = internal_token
        child_program = textwrap.dedent(
            f"""
            import asyncio

            from vaultspec_a2a.control.worker_management import (
                LazyWorkerSpawner,
                WorkerHealthProbe,
                probe_worker_health,
            )


            async def main() -> None:
                worker_url = {url!r}
                worker_body = {{
                    "status": "ok",
                    "service": "worker",
                    "gateway_url": "http://127.0.0.1:59999",
                }}
                spawner = LazyWorkerSpawner(
                    worker_url=worker_url,
                    worker_port={port},
                    auto_spawn=True,
                )
                await spawner.ensure_worker()
                assert spawner.spawned is False
                assert spawner.process is None
                assert await probe_worker_health(worker_url) == WorkerHealthProbe(
                    healthy=True,
                    body=worker_body,
                )
                print("WORKER_PROVENANCE_SUBPROCESS_OK")


            asyncio.run(main())
            """
        )
        child = subprocess.run(
            [sys.executable, "-c", child_program],
            capture_output=True,
            check=False,
            cwd=tmp_path,
            env=child_environment,
            text=True,
            timeout=30,
        )
    assert child.returncode == 0, child.stderr
    assert child.stdout == "WORKER_PROVENANCE_SUBPROCESS_OK\n"
    assert observer == {
        "called": True,
        "authorization": expected_authorization,
    }
