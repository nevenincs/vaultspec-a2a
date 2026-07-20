"""Live coverage of the operator CLI against a real gateway.

The CLI is a thin HTTP client of the six-member gateway whitelist, so it is
proven the only honest way: run the real gateway app on a real socket (uvicorn
in a background thread) and invoke the CLI as a real subprocess (``python -m
vaultspec_a2a.cli.main``) pointed at it. The subprocess exercises the actual
console-script entry point end to end and issues real ``httpx`` requests to the
running server — no mocks, no in-process capture shims. It also confirms there is
no second code path: the CLI reaches the same ``/v1`` endpoints the engine uses.

A subprocess is used rather than click's ``CliRunner`` because the repo runs
pytest under ``--capture=sys``, which swaps ``sys.stdout`` at the Python level and
collides with CliRunner's own stdout swap, leaving its captured output empty. A
child process has its own clean stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, cast

import uvicorn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...api.tests.conftest import make_app
from ...database.models import Base
from ...lifecycle.discovery import service_json_path, write_service_json

if TYPE_CHECKING:
    from types import TracebackType

_PRESET = "mock-success-single"
_MODULE = "vaultspec_a2a.cli.main"


class _ThreadedServer:
    """Run a uvicorn server for *app* in a daemon thread on an ephemeral port."""

    def __init__(self, app: object) -> None:
        config = uvicorn.Config(
            cast("Any", app),
            host="127.0.0.1",
            port=0,
            log_level="warning",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.base = ""

    def __enter__(self) -> _ThreadedServer:
        self._thread.start()
        for _ in range(500):
            if self._server.started and self._server.servers:
                break
            time.sleep(0.01)
        if not (self._server.started and self._server.servers):
            raise RuntimeError("uvicorn did not start")
        port = self._server.servers[0].sockets[0].getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


class _GatewayFixture:
    """Build the real gateway app on a dedicated loop and keep its DB alive."""

    def __init__(self, tmp_path: Any) -> None:
        self._tmp = tmp_path
        self._loop = asyncio.new_event_loop()
        self._cp_cm: Any = None
        self._engine: Any = None
        self.app: Any = None
        self.worker: Any = None

    def __enter__(self) -> _GatewayFixture:
        self._engine = self._loop.run_until_complete(self._make_engine())
        session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._cp_cm = AsyncSqliteSaver.from_conn_string(
            str(self._tmp / "checkpoints.db")
        )
        checkpointer = self._loop.run_until_complete(self._cp_cm.__aenter__())
        self.app, _agg, self.worker, _cp = make_app(session_factory, checkpointer)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._cp_cm is not None:
            self._loop.run_until_complete(self._cp_cm.__aexit__(None, None, None))
        if self._engine is not None:
            self._loop.run_until_complete(self._engine.dispose())
        self._loop.close()

    async def _make_engine(self) -> Any:
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._tmp / 'test.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return engine


def _run_cli(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the operator CLI as a real child process."""
    return subprocess.run(
        [sys.executable, "-m", _MODULE, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_cli_uses_matching_loopback_discovery_token(tmp_path: Any) -> None:
    """A separate CLI process authenticates from the resident service record."""
    token = "cli-discovery-token"
    with _GatewayFixture(tmp_path) as gw:
        gw.app.state.v1_service_token = token
        gw.app.state.allow_unauthenticated_v1_for_testing = False
        with _ThreadedServer(gw.app) as srv:
            port = int(srv.base.rsplit(":", 1)[1])
            a2a_home = tmp_path / "cli-a2a-home"
            write_service_json(
                service_json_path(a2a_home),
                port=port,
                pid=os.getpid(),
                service_token=token,
            )
            environment = os.environ.copy()
            environment.pop("VAULTSPEC_INTERNAL_TOKEN", None)
            environment["VAULTSPEC_A2A_HOME"] = str(a2a_home)
            result = _run_cli("presets", "--url", srv.base, env=environment)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["api_version"] == "v1"


def test_configured_cli_token_precedes_matching_discovery_token(tmp_path: Any) -> None:
    """Explicit operator configuration remains the authentication authority."""
    configured = "configured-cli-token"
    with _GatewayFixture(tmp_path) as gw:
        gw.app.state.v1_service_token = configured
        gw.app.state.allow_unauthenticated_v1_for_testing = False
        with _ThreadedServer(gw.app) as srv:
            port = int(srv.base.rsplit(":", 1)[1])
            a2a_home = tmp_path / "configured-cli-a2a-home"
            write_service_json(
                service_json_path(a2a_home),
                port=port,
                pid=os.getpid(),
                service_token="discovery-token-must-not-win",
            )
            environment = os.environ.copy()
            environment.pop("VAULTSPEC_INTERNAL_TOKEN", None)
            environment["VAULTSPEC_A2A_HOME"] = str(a2a_home)
            environment["VAULTSPEC_A2A_GATEWAY_TOKEN"] = configured
            result = _run_cli("presets", "--url", srv.base, env=environment)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["api_version"] == "v1"


def test_cli_verbs_against_live_gateway(tmp_path: Any) -> None:
    with _GatewayFixture(tmp_path) as gw, _ThreadedServer(gw.app) as srv:
        # presets-list
        presets = _run_cli("presets", "--url", srv.base)
        assert presets.returncode == 0, presets.stderr
        pbody = json.loads(presets.stdout)
        assert pbody["api_version"] == "v1"
        assert any(p["id"] == _PRESET for p in pbody["presets"])

        # doctor (service-state)
        doctor = _run_cli("doctor", "--url", srv.base)
        assert doctor.returncode == 0, doctor.stderr
        assert json.loads(doctor.stdout)["api_version"] == "v1"

        # run start -> status -> cancel
        start = _run_cli(
            "run",
            "start",
            "--preset",
            _PRESET,
            "--message",
            "build it",
            "--autonomous",
            "--url",
            srv.base,
        )
        assert start.returncode == 0, start.stderr
        run_id = json.loads(start.stdout)["run_id"]
        assert run_id
        assert gw.worker.dispatches, "run start must dispatch to the worker"

        status = _run_cli("run", "status", run_id, "--url", srv.base)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)["run_id"] == run_id

        cancel = _run_cli("run", "cancel", run_id, "--url", srv.base)
        assert cancel.returncode == 0, cancel.stderr
        assert json.loads(cancel.stdout)["api_version"] == "v1"

        # unknown run -> non-zero exit with the error body printed
        missing = _run_cli("run", "status", "nope", "--url", srv.base)
        assert missing.returncode == 1


def test_doctor_flags_a_resident_missing_a_route(tmp_path: Any) -> None:
    """A real server genuinely missing a route reads as a stale resident.

    Simulates a resident gateway process started before ``run-stream``
    landed by removing that route from the real, already-registered gateway
    router (not a mock — a real route table with one fewer real entry,
    exactly what an old process serves since there is no hot-reload) and
    asserting doctor's diff against the installed source catches it. The
    doctor CLI runs as a real subprocess with its own freshly-built app, so
    its "expected" signature is unaffected by this process's mutation.

    ``gateway_router`` is a module-level singleton every ``create_app()``
    call shares, so the removed route is restored in a ``finally`` to avoid
    leaking the mutation into other tests in this process.
    """
    from ...api.routes.gateway import router as gateway_router

    stream_path = "/v1/runs/{run_id}/stream"
    with _GatewayFixture(tmp_path) as gw:
        stale_index = next(
            i
            for i, route in enumerate(gateway_router.routes)
            if getattr(route, "path", None) == stream_path
        )
        stale_route = gateway_router.routes.pop(stale_index)
        try:
            with _ThreadedServer(gw.app) as srv:
                doctor = _run_cli("doctor", "--url", srv.base)
                # A distinct non-zero exit (not the generic transport-error 1)
                # so automation catches a stale resident without parsing JSON.
                assert doctor.returncode == 3, doctor.stderr
                body = json.loads(doctor.stdout)
                assert body["stale_resident"] is True
                assert f"GET {stream_path}" in body["missing_routes"]
        finally:
            gateway_router.routes.insert(stale_index, stale_route)


def test_cli_reports_unreachable_gateway_cleanly() -> None:
    """A dead gateway yields a clean error and a non-zero exit, not a traceback."""
    # Port 1 is not listening; the transport error must be handled, not raised.
    result = _run_cli("presets", "--url", "http://127.0.0.1:1")
    assert result.returncode != 0
    assert "could not reach the gateway" in (result.stdout + result.stderr)


def test_cli_reports_installed_package_version() -> None:
    """``--version`` prints the resolved distribution version and exits clean.

    No gateway is needed: the flag resolves against installed metadata, so the
    expected value is derived from the same authority the CLI reports from
    rather than a hardcoded literal that would drift from the package version.
    """
    from vaultspec_a2a.utils import package_version

    result = _run_cli("--version")
    assert result.returncode == 0, result.stderr
    assert package_version() in result.stdout
