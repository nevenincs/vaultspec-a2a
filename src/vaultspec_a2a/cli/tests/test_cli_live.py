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

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...api.tests.conftest import SEATED_ATTACH_TOKEN, make_app
from ...lifecycle.discovery import service_json_path, write_service_json
from ...testing import (
    fetch_in_process_selection_at,
    run_cli,
    serve_on_loopback_in_thread,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_PRESET = "mock-success-single"


def _in_process_lane_arguments(base: str) -> dict[str, str]:
    """Return the provider/mode/entry arguments naming a served in-process lane.

    A TEST may choose an entry; production code may not. What is asserted by
    using it here is that the CLI carries the caller's choice through to the
    gateway intact, not that any particular model is right - so the choice must
    be a lane that bills nothing, which is the one guarantee the shared
    mechanism makes.

    Only three of the reference's fields are returned. The CLI's own resolver
    reads the catalog and supplies the revision, and that resolution is part of
    what this test exercises; handing it a revision would skip it.
    """
    selection = fetch_in_process_selection_at(
        base,
        str(Path.cwd()),
        headers={"Authorization": f"Bearer {SEATED_ATTACH_TOKEN}"},
    )
    return {
        key: str(selection[key])
        for key in ("provider_id", "execution_mode", "entry_id")
    }


# Blank rather than absent: ``run_cli`` overlays the inherited environment and the
# settings source ignores empty values, so the child never holds the worker
# credential of a host that exports one.
_NO_WORKER_CREDENTIAL = {"VAULTSPEC_A2A_INTERNAL_TOKEN": ""}

# A configured token is the CLI's authoritative credential, so a child run in
# this environment authenticates against a gateway built by ``make_app``.
_SEATED_TOKEN_ENV = {
    **_NO_WORKER_CREDENTIAL,
    "VAULTSPEC_A2A_GATEWAY_TOKEN": SEATED_ATTACH_TOKEN,
}


def test_cli_uses_matching_loopback_discovery_token(
    tmp_path: Any,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A separate CLI process authenticates from the resident service record."""
    token = "cli-discovery-token"
    app = make_app(session_factory, checkpointer, stamp_credentials=False)[0]
    app.state.v1_service_token = token
    with serve_on_loopback_in_thread(app) as base:
        port = int(base.rsplit(":", 1)[1])
        a2a_home = tmp_path / "cli-a2a-home"
        write_service_json(
            service_json_path(a2a_home),
            port=port,
            pid=os.getpid(),
            service_token=token,
        )
        result = run_cli(
            "presets",
            "--url",
            base,
            env={**_NO_WORKER_CREDENTIAL, "VAULTSPEC_A2A_HOME": str(a2a_home)},
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["api_version"] == "v1"


def test_configured_cli_token_precedes_matching_discovery_token(
    tmp_path: Any,
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Explicit operator configuration remains the authentication authority."""
    configured = "configured-cli-token"
    app = make_app(session_factory, checkpointer, stamp_credentials=False)[0]
    app.state.v1_service_token = configured
    with serve_on_loopback_in_thread(app) as base:
        port = int(base.rsplit(":", 1)[1])
        a2a_home = tmp_path / "configured-cli-a2a-home"
        write_service_json(
            service_json_path(a2a_home),
            port=port,
            pid=os.getpid(),
            service_token="discovery-token-must-not-win",
        )
        result = run_cli(
            "presets",
            "--url",
            base,
            env={
                **_NO_WORKER_CREDENTIAL,
                "VAULTSPEC_A2A_HOME": str(a2a_home),
                "VAULTSPEC_A2A_GATEWAY_TOKEN": configured,
            },
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["api_version"] == "v1"


def test_cli_verbs_against_live_gateway(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    app, _aggregator, worker, _checkpointer = make_app(
        session_factory, checkpointer, stamp_credentials=False
    )
    with serve_on_loopback_in_thread(app) as base:
        # presets-list
        presets = run_cli("presets", "--url", base, env=_SEATED_TOKEN_ENV)
        assert presets.returncode == 0, presets.stdout + presets.stderr
        pbody = json.loads(presets.stdout)
        assert pbody["api_version"] == "v1"
        assert any(p["id"] == _PRESET for p in pbody["presets"])

        # doctor (service-state)
        doctor = run_cli("doctor", "--url", base, env=_SEATED_TOKEN_ENV)
        assert doctor.returncode == 0, doctor.stdout + doctor.stderr
        assert json.loads(doctor.stdout)["api_version"] == "v1"

        # run start -> status -> cancel
        # The operator names the lane and entry; the CLI resolves only the
        # catalog revision. Read here from the same served catalog rather than
        # hardcoded, so this proves the real end-to-end path.
        catalog = run_cli("presets", "--url", base, env=_SEATED_TOKEN_ENV)
        assert catalog.returncode == 0, catalog.stdout + catalog.stderr
        lane = _in_process_lane_arguments(base)
        start = run_cli(
            "run",
            "start",
            "--preset",
            _PRESET,
            "--message",
            "build it",
            "--provider",
            lane["provider_id"],
            "--execution-mode",
            lane["execution_mode"],
            "--entry",
            lane["entry_id"],
            "--autonomous",
            "--url",
            base,
            env=_SEATED_TOKEN_ENV,
        )
        assert start.returncode == 0, start.stdout + start.stderr
        run_id = json.loads(start.stdout)["run_id"]
        assert run_id
        assert worker.dispatches, "run start must dispatch to the worker"

        status = run_cli("run", "status", run_id, "--url", base, env=_SEATED_TOKEN_ENV)
        assert status.returncode == 0, status.stdout + status.stderr
        assert json.loads(status.stdout)["run_id"] == run_id

        cancel = run_cli("run", "cancel", run_id, "--url", base, env=_SEATED_TOKEN_ENV)
        assert cancel.returncode == 0, cancel.stdout + cancel.stderr
        assert json.loads(cancel.stdout)["api_version"] == "v1"

        # unknown run -> non-zero exit with the error body printed
        missing = run_cli("run", "status", "nope", "--url", base, env=_SEATED_TOKEN_ENV)
        assert missing.returncode == 1


def test_doctor_flags_a_resident_missing_a_route(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
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
    app = make_app(session_factory, checkpointer, stamp_credentials=False)[0]
    stale_index = next(
        i
        for i, route in enumerate(gateway_router.routes)
        if getattr(route, "path", None) == stream_path
    )
    stale_route = gateway_router.routes.pop(stale_index)
    try:
        with serve_on_loopback_in_thread(app) as base:
            doctor = run_cli("doctor", "--url", base, env=_SEATED_TOKEN_ENV)
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
    result = run_cli("presets", "--url", "http://127.0.0.1:1", env=_SEATED_TOKEN_ENV)
    assert result.returncode != 0
    assert "could not reach the gateway" in (result.stdout + result.stderr)


def test_cli_reports_installed_package_version() -> None:
    """``--version`` prints the resolved distribution version and exits clean.

    No gateway is needed: the flag resolves against installed metadata, so the
    expected value is derived from the same authority the CLI reports from
    rather than a hardcoded literal that would drift from the package version.
    """
    from ...utils import package_version

    result = run_cli("--version")
    assert result.returncode == 0, result.stdout + result.stderr
    assert package_version() in result.stdout
