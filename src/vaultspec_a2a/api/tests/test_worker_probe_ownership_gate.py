"""The request-path worker probes prove ownership before they spend the bearer.

Both request-path surfaces - the service health aggregate and the run-admission
readiness probe - reach the worker through the app-pooled client, and that client
carries the worker interprocess-communication bearer in its default headers. So
"probe the worker port" and "hand this gateway's credential to whatever holds the
worker port" are the same act, and ownership has to be settled first: only a
listener inside the owner's process tree may receive it.

The occupant here is a real loopback HTTP server that records every request it
receives, including the Authorization header, and the owner is a real live
process whose tree does not contain it - the relation a port squatter or another
stack's worker presents. An empty request log is the only evidence that
distinguishes a probe that was never sent from one sent without the bearer, so
the last test proves the bearer really is on that client.
"""

from __future__ import annotations

import contextlib
import http.server
import subprocess
import sys
from typing import TYPE_CHECKING, Any, TypedDict, cast

import httpx
import pytest
from httpx import ASGITransport

from ...control._worker_health import internal_auth_headers
from ...control.worker_management import LazyWorkerSpawner
from ...testing import JsonReplyHandler, serve_handler, settings_override
from ...utils import ProcessContainment, bearer_header, reap_contained, spawn_contained
from ..routes.gateway import _probe_admission_readiness
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# The worker IPC secret the gateway under test holds while it inspects the port.
_WORKER_TOKEN = "worker-probe-ownership-token"

# A body that passes the shared worker-readiness rule, so an ungated probe would
# promote this occupant to a ready worker rather than merely reaching it.
_READY_WORKER_BODY: dict[str, object] = {"status": "ok", "service": "worker"}


class _ReceivedRequest(TypedDict):
    """One request the loopback occupant actually received."""

    method: str
    path: str
    authorization: str | None


def _recording_handler(
    received: list[_ReceivedRequest],
) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received.append(
                {
                    "method": "GET",
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            if self.path != "/health":
                self._reply_empty(404)
                return
            self._reply(200, _READY_WORKER_BODY)

    return _Handler


@contextlib.contextmanager
def _foreign_owner() -> Generator[tuple[subprocess.Popen[bytes], ProcessContainment]]:
    """A real live process, with its containment, whose tree holds no listener."""
    containment = ProcessContainment.create()
    process = spawn_contained(
        [
            getattr(sys, "_base_executable", sys.executable),
            "-c",
            "import time; time.sleep(300)",
        ],
        containment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield process, containment
    finally:
        assert reap_contained(process, containment, term_timeout=2.0, kill_timeout=2.0)


@contextlib.asynccontextmanager
async def _gateway_facing_a_foreign_occupant(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: Any
) -> AsyncGenerator[tuple[FastAPI, list[_ReceivedRequest]]]:
    """A real gateway whose configured worker port is held outside its tree.

    The spawner is a production ``LazyWorkerSpawner`` seated on a real process it
    owns, which is what makes its ownership root a pid the occupant is provably
    outside of. Its pooled client is built exactly as the gateway lifespan builds
    it, bearer in the default headers, and closed here because this app is built
    without the lifespan that would otherwise own it.
    """
    received: list[_ReceivedRequest] = []
    with serve_handler(_recording_handler(received)) as port:
        worker_url = f"http://127.0.0.1:{port}"
        with (
            settings_override(
                worker_url=worker_url,
                worker_port=port,
                internal_token=_WORKER_TOKEN,
            ),
            _foreign_owner() as (owner, containment),
        ):
            app, _relay_hub, _worker, _checkpointer = make_app(
                session_factory, checkpointer
            )
            assert app.state.internal_token == _WORKER_TOKEN
            spawner = LazyWorkerSpawner(
                worker_url=worker_url,
                worker_port=port,
                auto_spawn=True,
                internal_token=_WORKER_TOKEN,
            )
            spawner.replace_process(owner, containment)
            assert spawner.owner_pid == owner.pid
            app.state.worker_spawner = spawner
            async with httpx.AsyncClient(
                base_url=worker_url,
                timeout=httpx.Timeout(30.0, connect=5.0),
                headers=internal_auth_headers(_WORKER_TOKEN),
            ) as client:
                app.state.worker_client = client
                yield app, received


async def _service_health(app: FastAPI) -> dict[str, Any]:
    """Call the real ``/health`` endpoint and return its decoded body."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


@pytest.mark.asyncio
async def test_service_health_withholds_the_bearer_from_a_foreign_occupant(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: Any
) -> None:
    """``/health`` sends nothing to a worker port its owner's tree does not hold.

    The occupant would answer as a fully ready worker, so an ungated aggregate
    reports it ``ok`` - adopting a stranger's readiness as its own worker's, and
    paying for that answer with the bearer. The gated aggregate reports the
    worker exactly as unreachable, which is what it is: this gateway has no
    worker it can prove.
    """
    async with _gateway_facing_a_foreign_occupant(session_factory, checkpointer) as (
        app,
        received,
    ):
        body = await _service_health(app)

    assert received == []
    assert body["checks"]["worker"] == {
        "status": "error",
        "detail": "worker probe failed",
    }


@pytest.mark.asyncio
async def test_run_admission_withholds_the_bearer_from_a_foreign_occupant(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: Any
) -> None:
    """Run admission never credentials the port to learn whether it is ready.

    A withheld probe is a decisive non-observation of this gateway's worker, not
    an unfinished one, so the worker reads as not yet serving rather than as the
    ready worker the occupant would otherwise have been taken for.
    """
    async with _gateway_facing_a_foreign_occupant(session_factory, checkpointer) as (
        app,
        received,
    ):
        readiness = await _probe_admission_readiness(app.state, app.state.worker_client)

    assert received == []
    assert readiness.worker_state.value == "starting"
    assert readiness.run_admission.value != "ready"


@pytest.mark.asyncio
async def test_the_pooled_client_really_spends_the_bearer_on_the_worker_port(
    session_factory: async_sessionmaker[AsyncSession], checkpointer: Any
) -> None:
    """The credential the gate withholds is genuinely on every pooled request.

    Without this, the two assertions above would hold just as well for a client
    that never carried a credential, and the gate would be proving nothing.
    """
    async with _gateway_facing_a_foreign_occupant(session_factory, checkpointer) as (
        app,
        received,
    ):
        response = await app.state.worker_client.get("/health")

    assert response.status_code == 200
    assert received == [
        {
            "method": "GET",
            "path": "/health",
            "authorization": bearer_header(_WORKER_TOKEN)["Authorization"],
        }
    ]
