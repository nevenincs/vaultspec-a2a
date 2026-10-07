"""Public spawn-path proof for worker provenance and held-port safety.

Real loopback HTTP servers, no mocks. A worker's health response is useful only
when its declaration proves that it belongs to this gateway. These tests drive
the public health probe and lazy spawner, rather than reaching into their
classification and eviction helpers.
"""

from __future__ import annotations

import http.server
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypedDict

import pytest

from ...control._worker_health import WorkerHealthProbe, probe_worker_health
from ...control.config import settings
from ...control.infra_config import INTERNAL_TOKEN_ENV
from ...control.worker_management import LazyWorkerSpawner
from ...testing import JsonReplyHandler, inherited_environment, serve_handler
from ...utils import bearer_header
from ...utils._process_tree import port_has_listener

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


# The IPC secret the gateway under test holds while it inspects a worker port.
_EVICTION_TOKEN = "foreign-eviction-token"


class _ReceivedRequest(TypedDict):
    """One request the loopback occupant actually received."""

    method: str
    path: str
    authorization: str | None


class _ShutdownObservation(TypedDict):
    called: bool
    authorization: str | None


def _make_handler(
    body: dict[str, object] | None,
    shutdown_log: _ShutdownObservation,
    received: list[_ReceivedRequest],
) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
        def _record(self, method: str) -> None:
            received.append(
                {
                    "method": method,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                }
            )

        def do_GET(self) -> None:
            self._record("GET")
            if self.path != "/health" or body is None:
                self._reply_empty(404)
                return
            self._reply(200, body)

        def do_POST(self) -> None:
            self._record("POST")
            if self.path != "/admin/shutdown":
                self._reply_empty(404)
                return
            shutdown_log["called"] = True
            shutdown_log["authorization"] = self.headers.get("Authorization")
            self._reply_empty(202)

    return _Handler


@contextmanager
def _worker_like(
    body: dict[str, object] | None,
) -> Generator[tuple[str, int, _ShutdownObservation]]:
    with _observed_worker_like(body) as (url, port, shutdown_log, _received):
        yield url, port, shutdown_log


@contextmanager
def _observed_worker_like(
    body: dict[str, object] | None,
) -> Generator[tuple[str, int, _ShutdownObservation, list[_ReceivedRequest]]]:
    """A real loopback occupant that records EVERY request it receives.

    The request log is the evidence a credential-withholding assertion needs: a
    probe the gateway never sent and a probe it sent without the bearer are
    different facts, and only the full log tells them apart.
    """
    shutdown_log: _ShutdownObservation = {"called": False, "authorization": None}
    received: list[_ReceivedRequest] = []
    with serve_handler(_make_handler(body, shutdown_log, received)) as port:
        yield f"http://127.0.0.1:{port}", port, shutdown_log, received


@pytest.mark.asyncio
async def test_probe_worker_health_returns_body_with_gateway_target() -> None:
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:8000",
    }
    with _worker_like(body) as (url, _port, _log):
        probe = await probe_worker_health(url, internal_token=None)
    assert probe == WorkerHealthProbe(healthy=True, body=body)


@pytest.mark.asyncio
async def test_probe_worker_health_reports_unreachable_as_unhealthy_without_body() -> (
    None
):
    assert await probe_worker_health(
        "http://127.0.0.1:9", internal_token=None
    ) == WorkerHealthProbe(
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
        spawner = LazyWorkerSpawner(
            worker_url=url, worker_port=port, auto_spawn=False, internal_token=None
        )
        await spawner.ensure_worker()
    assert spawner.spawned is True
    assert spawner.process is None


@pytest.mark.asyncio
async def test_ensure_worker_refuses_missing_or_blank_target() -> None:
    """The public attach path requires explicit current gateway evidence."""
    without_target: dict[str, object] = {"status": "ok", "service": "worker"}
    with_blank_target: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "",
    }
    for body in (without_target, with_blank_target):
        with _worker_like(body) as (url, port, _log):
            spawner = LazyWorkerSpawner(
                worker_url=url,
                worker_port=port,
                auto_spawn=False,
                internal_token=None,
            )
            await spawner.ensure_worker()
        assert spawner.spawned is False
        assert spawner.process is None


@pytest.mark.asyncio
async def test_auto_spawn_does_not_evict_a_worker_without_target_evidence() -> None:
    body: dict[str, object] = {"status": "ok", "service": "worker"}
    with _worker_like(body) as (url, port, shutdown):
        spawner = LazyWorkerSpawner(
            worker_url=url,
            worker_port=port,
            auto_spawn=True,
            internal_token=None,
        )
        await spawner.ensure_worker()

    assert spawner.spawned is False
    assert spawner.process is None
    assert shutdown["called"] is False


@pytest.mark.asyncio
async def test_ensure_worker_refuses_a_foreign_worker_without_auto_spawn() -> None:
    """A public attach request never adopts a live foreign incumbent."""
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _worker_like(body) as (url, port, _log):
        spawner = LazyWorkerSpawner(
            worker_url=url, worker_port=port, auto_spawn=False, internal_token=None
        )
        await spawner.ensure_worker()
    assert spawner.spawned is False
    assert spawner.process is None


@pytest.mark.asyncio
async def test_ensure_worker_refuses_an_unreachable_worker_without_auto_spawn() -> None:
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9",
        worker_port=9,
        auto_spawn=False,
        internal_token=None,
    )
    await spawner.ensure_worker()
    assert spawner.spawned is False
    assert spawner.process is None


@pytest.mark.asyncio
async def test_an_unarmed_auto_spawn_gateway_never_evicts_a_foreign_worker() -> None:
    """A foreign-targeted occupant is a conflict, not something to terminate.

    The occupant here is a listener in THIS process, so the ownership gate reads
    it as ours and the credentialed health probe is legitimate - which is the
    point: what must not happen is the eviction. An unarmed gateway has no
    authority to terminate another process on the worker port, so it refuses the
    spawn and leaves the occupant running for whoever owns it (the dev-process
    registry reaps a stale orphan).
    """
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _observed_worker_like(body) as (url, port, log, received):
        spawner = LazyWorkerSpawner(
            worker_url=url,
            worker_port=port,
            auto_spawn=True,
            internal_token=_EVICTION_TOKEN,
        )
        await spawner.ensure_worker()
        sent_by_the_gateway = list(received)
        still_healthy = await probe_worker_health(url, internal_token=None)
    assert log == {"called": False, "authorization": None}
    # The occupant is this process's own listener, so every probe it did receive
    # legitimately carried the bearer; none of them reached /admin/shutdown.
    assert {request["path"] for request in sent_by_the_gateway} == {"/health"}
    assert {request["authorization"] for request in sent_by_the_gateway} == {
        bearer_header(_EVICTION_TOKEN)["Authorization"]
    }
    assert still_healthy == WorkerHealthProbe(healthy=True, body=body)
    assert spawner.spawned is False
    assert spawner.process is None


def test_subprocess_auto_spawn_withholds_every_credential_from_a_foreign_tree(
    tmp_path: Path,
) -> None:
    """A gateway sends nothing at all to a worker port its own tree does not hold.

    The parent owns the occupant's real loopback listener; the gateway under test
    is a separate child process, so the listener sits outside that gateway's
    process tree exactly as a squatter or another stack's worker would. Ownership
    cannot be confirmed, so the port is a conflict: no credentialed probe, no
    adoption, no eviction - the occupant receives no request whatsoever, and the
    gateway refuses to spawn onto the held port.
    """
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _observed_worker_like(body) as (url, port, observer, received):
        child_environment = inherited_environment(
            {
                INTERNAL_TOKEN_ENV: "evict-secret",
                "VAULTSPEC_A2A_ENVIRONMENT": "development",
            }
        )
        child_program = textwrap.dedent(
            f"""
            import asyncio

            from vaultspec_a2a.control.config import settings
            from vaultspec_a2a.control.worker_management import LazyWorkerSpawner


            async def main() -> None:
                spawner = LazyWorkerSpawner(
                    worker_url={url!r},
                    worker_port={port},
                    auto_spawn=True,
                    internal_token=settings.internal_token,
                )
                await spawner.ensure_worker()
                assert spawner.spawned is False
                assert spawner.process is None
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
        seen_by_the_occupant = list(received)
        # Survival is read from the socket, not over HTTP, so confirming it
        # cannot itself add a request to the log under assertion.
        survived = port_has_listener(port, timeout=1.0)
    assert child.returncode == 0, child.stderr
    assert child.stdout == "WORKER_PROVENANCE_SUBPROCESS_OK\n"
    assert observer == {"called": False, "authorization": None}
    assert seen_by_the_occupant == []
    assert survived is True
