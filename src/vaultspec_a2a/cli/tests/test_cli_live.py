"""Live coverage of the operator CLI against a real gateway (ADR R9).

The CLI is a thin HTTP client of the five-verb surface, so it is proven the only
honest way: run the real gateway app on a real socket (uvicorn in a background
thread) and invoke the CLI as a real subprocess (``python -m
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


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the operator CLI as a real child process."""
    return subprocess.run(
        [sys.executable, "-m", _MODULE, *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


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


def test_cli_reports_unreachable_gateway_cleanly() -> None:
    """A dead gateway yields a clean error and a non-zero exit, not a traceback."""
    # Port 1 is not listening; the transport error must be handled, not raised.
    result = _run_cli("presets", "--url", "http://127.0.0.1:1")
    assert result.returncode != 0
    assert "could not reach the gateway" in (result.stdout + result.stderr)
