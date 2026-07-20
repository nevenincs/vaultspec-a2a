"""Certify two-stage run admission against a real armed desktop gateway.

A real child interpreter boots the production gateway armed with the desktop
profile over a genuinely migrated app home, with auto-spawn enabled so the
gateway owns and spawns its own worker. The parent then proves, over real
loopback sockets and HTTP, the run-admission invariants:

- concurrent prepares create exactly one real worker and enforce the hard
  reservation bound: with a capacity of two, four parallel authenticated prepares
  admit exactly two and refuse the rest, and the worker spawn line appears once;
- a prepare creates no durable run and receives no token: its response carries a
  reservation identity and the validated required-role set but no run id and no
  token, and active-run discovery stays empty, so no run - and therefore no
  run-owned child - is created;
- commit is reservation-bound: committing a live reservation creates exactly one
  run and consumes the reservation, a double commit is refused, and a bogus
  reservation is refused, each leaving no extra run;
- an uncommitted reservation times out and frees its bounded slot, and a commit
  against an expired reservation is refused and creates no run.

The valid database is seated by the real ``desktop-migrate`` entrypoint in a
separate process; the gateway is a second real process and the worker a third,
gateway-owned one. No mock, monkeypatch, stub, skip, or expected failure is used;
every child is reaped in a ``finally`` by killing the gateway process tree.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.transaction import package_migration_range
from vaultspec_a2a.utils import kill_pid_tree_async

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_ATTACH = "attach-credential-admission-1234567890abcdef"
_OWNERSHIP = "ownership-capability-admission-fedcba0987654321"
_DIGEST = "a" * 64
_MODULE = "vaultspec_a2a.cli.main"
_PRESET = "mock-success-single"
_REQUIRED_ROLE = "mock-coder-success"
_SPAWN_LINE = "Auto-spawning worker on port"

_GATEWAY = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""


def _seed_credentials(app_home: Path) -> None:
    """Write the dashboard-created attach and ownership files."""
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, _ATTACH),
        (OWNERSHIP_CAPABILITY_NAME, _OWNERSHIP),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)


def _write_descriptor(descriptor_path: Path, app_home: Path) -> Path:
    """Write a one-time migration descriptor for the app home's stores."""
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    document = {
        "descriptor_version": "1",
        "transaction_id": "admission-txn-1",
        "app_home": str(app_home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "4.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    return descriptor_path


def _seat_valid_database(app_home: Path, descriptor: Path) -> None:
    """Seat a valid desktop database via the real desktop-migrate entrypoint."""
    command = [
        sys.executable,
        "-m",
        _MODULE,
        "desktop-migrate",
        "--descriptor",
        str(descriptor),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "succeeded", payload
    assert derive_state_paths(app_home).database_path.is_file()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _await_health(base: str, *, timeout: float = 40.0) -> None:
    """Wait until the gateway's liveness endpoint answers 200."""
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:  # not up yet
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(f"gateway readiness never came up ({last})")


@contextmanager
def _armed_gateway(tmp_path: Path, **extra_env: str) -> Iterator[tuple[str, str]]:
    """Boot a real armed desktop gateway; yield ``(base_url, auth_header)``.

    Seats a real migrated app home, boots the production gateway armed with
    auto-spawn enabled, waits for liveness, and reaps the whole process tree on
    exit. ``extra_env`` overrides gateway environment (capacity, reservation TTL).
    """
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _seed_credentials(app_home)
    _seat_valid_database(app_home, _write_descriptor(tmp_path / "txn.json", app_home))

    gateway_port = _free_port()
    worker_port = _free_port()
    log_path = tmp_path / "gateway.log"
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(gateway_port)
    env["VAULTSPEC_WORKER_PORT"] = str(worker_port)
    env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "true"
    env.update(extra_env)

    base = f"http://127.0.0.1:{gateway_port}"
    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-c", _GATEWAY, str(gateway_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _await_health(base)
        yield base, f"Bearer {_ATTACH}"
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()


def _prepare(base: str, auth: str) -> tuple[int, dict[str, Any]]:
    """Fire one authenticated prepare and return its status and JSON body.

    Blocks inside the gateway until the single-flight worker start reaches
    readiness, so parallel calls model concurrent first demand.
    """
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={"team_preset": _PRESET, "stage": "prepare"},
        )
    return resp.status_code, resp.json()


def _commit(base: str, auth: str, reservation_id: str) -> tuple[int, dict[str, Any]]:
    """Fire one authenticated commit binding tokens under *reservation_id*."""
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={
                "team_preset": _PRESET,
                "stage": "commit",
                "reservation_id": reservation_id,
                "message": "build it",
                "autonomous": True,
                "actor_tokens": {
                    "tokens": {_REQUIRED_ROLE: "tok-coder"},
                    "engine_bearer": "bearer",
                },
            },
        )
    return resp.status_code, resp.json()


def _run_exists(base: str, auth: str, run_id: str) -> bool:
    """Return whether the gateway has a durable run under *run_id*.

    Uses run-status, which returns a run whether it is still active or already
    terminal - robust against a fast mock run completing before the check.
    """
    with httpx.Client(base_url=base, timeout=10.0) as client:
        resp = client.get(f"/v1/runs/{run_id}", headers={"Authorization": auth})
    return resp.status_code == 200


def _active_run_count(base: str, auth: str) -> int:
    """Return the number of active (non-terminal) runs the gateway discovers."""
    with httpx.Client(base_url=base, timeout=10.0) as client:
        resp = client.get("/v1/runs", headers={"Authorization": auth})
    assert resp.status_code == 200, resp.text
    return len(resp.json()["runs"])


def test_concurrent_prepare_bounds_capacity_and_commit_is_reservation_bound(
    tmp_path: Path,
) -> None:
    """Concurrent prepares bound capacity and start one worker; commit binds a run."""
    log_path = tmp_path / "gateway.log"
    with _armed_gateway(tmp_path, VAULTSPEC_MAX_CONCURRENT_THREADS="2") as (base, auth):
        # --- Concurrent first demand: hard reservation bound, one worker. ---
        # Four real parallel prepares race into the single-flight worker start and
        # the bounded reservation table (capacity two).
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: _prepare(base, auth), range(4)))
        statuses = sorted(status for status, _ in outcomes)
        assert statuses == [201, 201, 503, 503], statuses

        admitted = [body for status, body in outcomes if status == 201]
        reservations = [body["reservation_id"] for body in admitted]
        assert len(set(reservations)) == 2, reservations
        for body in admitted:
            # A prepare returns a reservation and the validated required roles, but
            # no run identity and no token - it creates no durable run.
            assert body["stage"] == "prepared"
            assert body["required_roles"] == [_REQUIRED_ROLE]
            assert "run_id" not in body
            assert "actor_tokens" not in body and "lease_id" not in body

        # No run - hence no run-owned child - was created by any prepare.
        assert _active_run_count(base, auth) == 0

        # --- Commit is reservation-bound. ---
        # Committing a live reservation creates exactly one durable run and consumes
        # the reservation; the response carries the run and its non-secret lease.
        status, body = _commit(base, auth, reservations[0])
        assert status == 201, (status, body)
        assert body["stage"] == "committed"
        assert body["run_id"] and body["lease_id"].startswith("lease-")
        assert _run_exists(base, auth, body["run_id"])

        # A double commit of the now-consumed reservation is refused before any run
        # is created (a refused commit never reaches run creation).
        again_status, _ = _commit(base, auth, reservations[0])
        assert again_status == 409, again_status

        # A bogus reservation is refused the same way.
        bogus_status, _ = _commit(base, auth, "resv-deadbeefdeadbeefdeadbeefdeadbeef")
        assert bogus_status == 409, bogus_status

    # Single-flight: the worker spawn line appears exactly once for the burst.
    spawn_count = log_path.read_text(encoding="utf-8", errors="replace").count(
        _SPAWN_LINE
    )
    assert spawn_count == 1, f"expected one worker spawn, saw {spawn_count}"


def test_reservation_times_out_and_expired_commit_creates_no_run(
    tmp_path: Path,
) -> None:
    """An uncommitted reservation expires, freeing capacity; expired commit refused."""
    with _armed_gateway(
        tmp_path,
        VAULTSPEC_MAX_CONCURRENT_THREADS="2",
        VAULTSPEC_ADMISSION_RESERVATION_TTL_SECONDS="3",
    ) as (base, auth):
        # Fill the bound: two reservations, then a third refused.
        first_status, first_body = _prepare(base, auth)
        second_status, _ = _prepare(base, auth)
        third_status, _ = _prepare(base, auth)
        assert first_status == 201 and second_status == 201, (
            first_status,
            second_status,
        )
        assert third_status == 503, third_status
        assert _active_run_count(base, auth) == 0

        # Wait past the reservation time-to-live: the uncommitted slots expire.
        time.sleep(5.0)

        # Capacity is free again - a fresh prepare is admitted.
        fourth_status, _ = _prepare(base, auth)
        assert fourth_status == 201, fourth_status

        # A commit against the now-expired first reservation is refused and creates
        # no run: a timed-out reservation leaks neither a slot nor a run.
        expired_status, _ = _commit(base, auth, first_body["reservation_id"])
        assert expired_status == 409, expired_status
        assert _active_run_count(base, auth) == 0
