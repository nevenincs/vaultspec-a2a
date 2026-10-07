"""Certify the desktop readiness model against a real armed gateway over HTTP.

A real child interpreter boots the production gateway armed with the desktop
profile over a genuinely migrated app home: ordinary boot validates the seated
schema, seats the database engine, and creates the lazy worker spawner without
starting a worker. The parent then proves, over a real loopback socket, that the
unauthenticated liveness boundary discloses only the minimal alive signal (asserted
byte-for-byte), that the readiness facts are reachable only through the attach
credential, and that a cold worker reads as gateway-ready with execution blocked
until an OS isolation backend is verified, on both the
authenticated liveness surface and the service-state verb.

The valid database is seated by the real ``migrate`` entrypoint in a
separate process; the gateway is a second real process. No mock, monkeypatch,
stub, skip, or expected failure is used; children are torn down when the test
ends.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx

from ..control.health import SERVICE_WORKER_PROBE_TIMEOUT_SECONDS
from ..testing import (
    DEFAULT_ATTACH_CREDENTIAL,
    RunVerbs,
    armed_gateway_env,
    booted_gateway,
    desktop_workspace,
    gateway_script,
    log_tail,
    seat_app_home,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..testing import BootedGateway

_AUTH = f"Bearer {DEFAULT_ATTACH_CREDENTIAL}"
# A read budget for a RESPONSE, not a latency assertion: the bounded-probe
# property is proven from the gateway's own probe measurement, and this only
# keeps a wedged gateway from hanging the session. The per-item pytest-timeout
# backstop remains the last-resort guard.
_SERVICE_READ_BUDGET_SECONDS = 60.0


def _gateway_failure_diagnostics(gateway: BootedGateway) -> str:
    """Preserve child exit and lifespan evidence when the real HTTP trace fails."""
    exit_code = gateway.process.poll()
    process_state = "still running" if exit_code is None else f"exited {exit_code}"
    tail = log_tail(gateway.log_path)
    return (
        f"gateway child {process_state}; log={gateway.log_path}; "
        f"lifespan/stderr tail:\n{tail or '<empty>'}"
    )


def _assert_readiness_surfaces(client: httpx.Client) -> None:
    """Assert minimal public liveness and authenticated cold readiness."""
    # --- Every ungated liveness surface is minimal, byte-for-byte. ---
    # Both the top-level probe and the aggregate probe must disclose only
    # the minimal alive signal - no process identity, service identity, or
    # product state. The body shape is asserted at the byte level so a
    # regression that re-adds a field cannot slip past a substring scan.
    leaks = (
        "pid",
        "generation",
        "profile",
        "worker",
        "gateway_readiness",
        "circuit",
        "backend",
        "status",
    )
    # The host's current cost for ONE trivial loopback round trip, measured on
    # the minimal liveness surface, which runs no probe at all. It is the
    # baseline the bounded-probe proof below adds its slack from, so that proof
    # scales with whatever this machine is doing instead of assuming an idle
    # one.
    trivial_started = time.monotonic()
    live = client.get("/health")
    trivial_round_trip_s = time.monotonic() - trivial_started
    assert live.status_code == 200
    assert live.content == b'{"liveness":"alive"}'
    assert live.json() == {"liveness": "alive"}
    for token in leaks:
        assert token not in live.text, token

    # --- Readiness facts are reachable only through the attach credential. ---
    assert client.get("/v1/service").status_code == 401

    # --- Authenticated readiness carries identity and the cold ladder. ---
    auth = {"Authorization": _AUTH}
    ready = client.get("/health", headers=auth)
    assert ready.status_code == 200
    body = ready.json()
    # Process identity is disclosed; the exact value is the real gateway
    # process, not this launcher handle (a venv python is a launcher stub
    # whose child pid differs), so identity is asserted present and
    # consistent across both authenticated surfaces below.
    gateway_pid = body["gateway_pid"]
    assert isinstance(gateway_pid, int) and gateway_pid > 0
    assert isinstance(body["generation"], str) and body["generation"]
    assert body["profile"] == "desktop"
    assert body["liveness"] == "alive"
    assert body["provider_eligibility"] == "ineligible"
    assert body["eligible_providers"] == []
    # Attachment is ready, but native execution lacks an OS isolation backend.
    assert body["gateway_readiness"] == "ready"
    assert body["worker_state"] == "cold"
    assert body["run_admission"] == "blocked"
    assert any("OS isolation backend" in reason for reason in body["reasons"])

    # --- The service-state verb serves the same readiness projection. ---
    # The production gateway intentionally boots with no worker. On Windows an
    # unbound loopback port can consume a connection's entire budget instead of
    # refusing promptly, so this real service request proves its worker probe is
    # bounded beneath the caller-facing budget rather than racing it.
    #
    # The bound is read from the gateway's OWN measurement of its probe phase,
    # not from a client budget shorter than the server's deadline. That
    # arrangement - a three-second client timeout in front of a server whose own
    # per-dependency deadline is also three seconds - made a busy host fail the
    # request by a read timeout, which proves nothing about the worker probe.
    svc = client.get("/v1/service", headers=auth, timeout=_SERVICE_READ_BUDGET_SECONDS)
    assert svc.status_code == 200
    service = svc.json()
    # The cold worker did not consume the caller's budget: the probe phase ended
    # at the worker probe's own bound, plus at most what one trivial round trip
    # costs on this host right now.
    probe_elapsed_s = service["probe_elapsed_ms"] / 1000
    assert (
        probe_elapsed_s
        <= SERVICE_WORKER_PROBE_TIMEOUT_SECONDS + trivial_round_trip_s + 1.0
    ), (service, trivial_round_trip_s)
    # The bounded observation must not pretend the cold worker is ready:
    # service-state remains truthful and declines run admission.
    assert service["status"] == "degraded"
    assert service["ready"] is False
    assert service["can_accept_run"] is False
    assert service["worker_ready"] is False
    readiness = service["readiness"]
    # Same real gateway process serves both authenticated surfaces.
    assert readiness["gateway_pid"] == gateway_pid
    assert readiness["gateway_readiness"] == "ready"
    assert readiness["worker_state"] == "cold"
    assert readiness["run_admission"] == "blocked"

    # Each new-run entry refuses before worker startup or capacity/token binding.
    workspace = desktop_workspace(str(client.base_url))
    selection = {
        "schema_version": 1,
        "provider_id": "codex",
        "execution_mode": "app_server",
        "catalog_revision": "unvalidated",
        "entry_id": "unvalidated",
    }
    verbs = RunVerbs(
        base_url=str(client.base_url),
        authorization=_AUTH,
        team_preset="mock-success-single",
        workspace_root=workspace,
        selection=lambda _workspace: selection,
        message="synthetic read",
    )
    for refusal in (
        verbs.start("native-isolation-start"),
        verbs.prepare("native-isolation-prepare"),
        verbs.commit(
            "native-isolation-commit",
            "unissued-reservation",
            tokens={"mock-coder-success": "synthetic-actor-token"},
        ),
    ):
        assert refusal.status_code == 503, refusal.text
        assert "OS isolation backend" in refusal.json()["detail"]
        assert "synthetic-actor-token" not in refusal.text
    runs = client.get("/v1/runs", headers=auth, params={"workspace_root": workspace})
    assert runs.status_code == 200
    assert runs.json()["runs"] == []
    after = client.get("/health", headers=auth).json()
    assert after["worker_state"] == "cold"
    assert after["gateway_readiness"] == "ready"


def test_desktop_readiness_liveness_minimal_and_readiness_authenticated(
    tmp_path: Path,
) -> None:
    """Minimal liveness is public; readiness with the cold ladder is authenticated."""
    app_home = tmp_path / "app-home"
    seat_app_home(app_home)
    # A real armed desktop gateway booting the *production* lifespan: create_app
    # runs the armed credential loading, and the production lifespan validates
    # the seated schema, seats the database engine, and creates the lazy worker
    # spawner. With auto-spawn disabled the worker stays cold, which is exactly
    # the fact under test: ordinary boot must not start it, so the gateway-ready
    # yet not-execution-ready fact is observable.
    # This gateway's INFO lifecycle messages are diagnostic evidence only: a
    # request failure must retain the real startup/shutdown trail and child exit
    # state instead of leaving a bare client timeout after a Popen exit.
    with (
        booted_gateway(
            armed_gateway_env(app_home, auto_spawn_worker=False),
            log_path=tmp_path / "gateway.log",
            script=gateway_script(log_level="info"),
        ) as gateway,
        httpx.Client(
            base_url=gateway.base_url, timeout=_SERVICE_READ_BUDGET_SECONDS
        ) as client,
    ):
        try:
            _assert_readiness_surfaces(client)
        except (httpx.HTTPError, AssertionError) as exc:
            raise AssertionError(
                "desktop readiness HTTP trace failed "
                f"({type(exc).__name__}: {exc}); "
                f"{_gateway_failure_diagnostics(gateway)}"
            ) from exc
