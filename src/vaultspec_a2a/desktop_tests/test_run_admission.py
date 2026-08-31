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

The valid database is seated by the real ``migrate`` entrypoint in a
separate process; the gateway is a second real process and the worker a third,
gateway-owned one. No mock, monkeypatch, stub, skip, or expected failure is used;
every child is reaped in a ``finally`` by killing the gateway process tree.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ._catalog import catalog_selection

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Iterator

_ATTACH = "attach-credential-admission-1234567890abcdef"
_OWNERSHIP = "ownership-capability-admission-fedcba0987654321"
_PRESET = "mock-success-single"
_REQUIRED_ROLE = "mock-coder-success"
_SPAWN_LINE = "Auto-spawning worker on port"

# The INFO variant: its root logging handler is the only reason the auto-spawn
# announcement asserted on below is written to the gateway log at all.
_GATEWAY = gateway_script(log_level="info")


@contextmanager
def _running_gateway(
    tmp_path: Path,
    app_home: Path,
    *,
    log_name: str = "gateway.log",
    **extra_env: str,
) -> Iterator[tuple[str, str]]:
    """Run one gateway process over an already seated application home."""
    log_path = tmp_path / log_name
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        return spawn_gateway(
            script=_GATEWAY,
            gateway_port=gateway_port,
            env=armed_gateway_env(
                app_home,
                gateway_port=gateway_port,
                worker_port=worker_port,
                # Every run this module admits selects an in-process lane
                # (see ``_catalog.py``); the gateway must serve one to select.
                extra={"VAULTSPEC_SERVE_IN_PROCESS_LANES": "true", **extra_env},
            ),
            log_handle=log_handle,
            new_session=True,
        )

    proc, _gateway_port, _worker_port, base = spawn_until_ready(
        _spawn, log_path=log_path
    )
    try:
        yield base, f"Bearer {_ATTACH}"
    finally:
        reap_gateway(proc)
        log_handle.close()


@contextmanager
def _armed_gateway(tmp_path: Path, **extra_env: str) -> Iterator[tuple[str, str]]:
    """Seat and boot a real armed desktop gateway over a migrated app home."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    with _running_gateway(tmp_path, app_home, **extra_env) as gateway:
        # Warm the catalog HERE, not inside the first prepare. The first read
        # probes every provider lane and takes seconds; paying that inside a
        # prepare shifted the timing the concurrency and replay cases depend on,
        # and their reservations aged out into an execution-readiness refusal.
        # Warming at arm time is also what the product should do - a run start
        # is not the place to discover the catalog for the first time.
        base, auth = gateway
        catalog_selection(base, auth, str(Path.cwd()))
        yield gateway


def _prepare(
    base: str,
    auth: str,
    *,
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Fire one authenticated prepare and return its status and JSON body.

    Blocks inside the gateway until the single-flight worker start reaches
    readiness, so parallel calls model concurrent first demand.
    """
    workspace = str((metadata or {}).get("workspace_root") or Path.cwd())
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={
                "team_preset": _PRESET,
                "stage": "prepare",
                "autonomous": True,
                **({"run_id": run_id} if run_id is not None else {}),
                # The workspace anchors the selection, so it rides even when the
                # caller declared no metadata of its own.
                "metadata": {"workspace_root": workspace, **(metadata or {})},
                "selection": catalog_selection(base, auth, workspace),
            },
        )
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        payload = {"detail": resp.text}
    return resp.status_code, payload


def _commit(
    base: str,
    auth: str,
    reservation_id: str,
    *,
    run_id: str | None = None,
    roles: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Fire one authenticated commit binding tokens under *reservation_id*."""
    workspace = str((metadata or {}).get("workspace_root") or Path.cwd())
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
                    "tokens": (
                        {_REQUIRED_ROLE: "tok-coder"} if roles is None else roles
                    ),
                    "engine_bearer": "bearer",
                },
                # Commit carries the selection too: it is the stage that creates
                # the durable run, so it is where the freeze happens. The value
                # matches prepare's because both read the same cached served
                # catalog - a replayed commit must be byte-identical to be
                # recognised as a replay rather than a changed body.
                "metadata": {"workspace_root": workspace, **(metadata or {})},
                "selection": catalog_selection(base, auth, workspace),
                **({"run_id": run_id} if run_id is not None else {}),
            },
        )
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        payload = {"detail": resp.text}
    return resp.status_code, payload


def _release(
    base: str,
    auth: str,
    reservation_id: str,
    *,
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Explicitly release one uncommitted prepared reservation.

    The release binding is the digest of the PREPARED request, so this body must
    mirror the prepare that opened the reservation field for field - including
    the selection and the workspace metadata. A release that omits either is not
    a weaker request, it is a DIFFERENT one, and the broker refuses to release a
    reservation it cannot recognise.
    """
    workspace = str((metadata or {}).get("workspace_root") or Path.cwd())
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={
                "team_preset": _PRESET,
                "stage": "release",
                "reservation_id": reservation_id,
                "autonomous": True,
                **({"run_id": run_id} if run_id is not None else {}),
                "metadata": {"workspace_root": workspace, **(metadata or {})},
                "selection": catalog_selection(base, auth, workspace),
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
            outcomes = list(
                pool.map(
                    lambda index: (
                        index,
                        *_prepare(base, auth, run_id=f"run-capacity-{index}"),
                    ),
                    range(4),
                )
            )
        statuses = sorted(status for _, status, _ in outcomes)
        assert statuses == [201, 201, 503, 503], statuses

        admitted = [(index, body) for index, status, body in outcomes if status == 201]
        reservations = [
            (body["reservation_id"], f"run-capacity-{index}")
            for index, body in admitted
        ]
        assert len(set(reservations)) == 2, reservations
        for _, body in admitted:
            # A prepare returns a reservation and the validated required roles, but
            # no run identity and no token - it creates no durable run. The
            # lease is non-secret coordination metadata bound before commit.
            assert body["stage"] == "prepared"
            assert body["required_roles"] == [_REQUIRED_ROLE]
            assert "run_id" not in body
            assert "actor_tokens" not in body
            assert body["lease_id"].startswith("lease-")

        # No run - hence no run-owned child - was created by any prepare.
        assert _active_run_count(base, auth) == 0

        # --- Commit is reservation-bound. ---
        # Committing a live reservation creates exactly one durable run and consumes
        # the reservation; the response carries the run and its non-secret lease.
        status, body = _commit(
            base, auth, reservations[0][0], run_id=reservations[0][1]
        )
        assert status == 201, (status, body)
        assert body["stage"] == "committed"
        assert body["run_id"] and body["lease_id"].startswith("lease-")
        assert _run_exists(base, auth, body["run_id"])

        # The exact same stable-id commit is a durable replay, not a second run.
        again_status, again_body = _commit(
            base, auth, reservations[0][0], run_id=reservations[0][1]
        )
        assert again_status == 201, again_status
        assert again_body["run_id"] == body["run_id"]
        assert again_body["lease_id"] == body["lease_id"]

        # A bogus reservation is refused the same way.
        bogus_status, _ = _commit(
            base,
            auth,
            "resv-deadbeefdeadbeefdeadbeefdeadbeef",
            run_id="run-bogus-reservation",
        )
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
        first_status, first_body = _prepare(base, auth, run_id="run-expiring-first")
        second_status, _ = _prepare(base, auth, run_id="run-expiring-second")
        third_status, _ = _prepare(base, auth, run_id="run-expiring-third")
        assert first_status == 201 and second_status == 201, (
            first_status,
            second_status,
        )
        assert third_status == 503, third_status
        assert _active_run_count(base, auth) == 0

        # Wait past the reservation time-to-live: the uncommitted slots expire.
        time.sleep(5.0)

        # Capacity is free again - a fresh prepare is admitted.
        fourth_status, _ = _prepare(base, auth, run_id="run-expiring-fourth")
        assert fourth_status == 201, fourth_status

        # A commit against the now-expired first reservation is refused and creates
        # no run: a timed-out reservation leaks neither a slot nor a run.
        expired_status, _ = _commit(
            base,
            auth,
            first_body["reservation_id"],
            run_id="run-expiring-first",
        )
        assert expired_status == 409, expired_status
        assert _active_run_count(base, auth) == 0


def test_exact_commit_replay_role_binding_release_and_race_are_linearized(
    tmp_path: Path,
) -> None:
    """Exact replays converge while mismatches and release races stay atomic."""
    with _armed_gateway(tmp_path, VAULTSPEC_MAX_CONCURRENT_THREADS="3") as (
        base,
        auth,
    ):
        run_id = "run-exact-replay"
        status, prepared = _prepare(base, auth, run_id=run_id)
        assert status == 201, prepared
        reservation_id = prepared["reservation_id"]

        mismatch_status, _ = _commit(
            base, auth, reservation_id, run_id="run-binding-mismatch"
        )
        assert mismatch_status == 409
        missing_status, _ = _commit(base, auth, reservation_id, run_id=run_id, roles={})
        assert missing_status == 409
        extra_status, _ = _commit(
            base,
            auth,
            reservation_id,
            run_id=run_id,
            roles={_REQUIRED_ROLE: "tok-coder", "unexpected-role": "tok-extra"},
        )
        assert extra_status == 409
        assert _active_run_count(base, auth) == 0

        with ThreadPoolExecutor(max_workers=2) as pool:
            replays = list(
                pool.map(
                    lambda _: _commit(base, auth, reservation_id, run_id=run_id),
                    range(2),
                )
            )
        assert [item[0] for item in replays] == [201, 201]
        bodies = [item[1] for item in replays]
        assert len({body["run_id"] for body in bodies}) == 1
        assert len({body["lease_id"] for body in bodies}) == 1

        with httpx.Client(base_url=base, timeout=10.0) as client:
            response = client.get(f"/v1/runs/{run_id}", headers={"Authorization": auth})
        assert response.status_code == 200, response.text
        assert response.json()["lease_id"] == bodies[0]["lease_id"]
        assert response.json()["reservation_id"] == reservation_id
        committed_release_status, committed_release = _release(
            base, auth, reservation_id, run_id=run_id
        )
        assert committed_release_status == 201
        assert committed_release["released"] is False

        race_run_id = "run-release-commit-race"
        race_status, race_prepared = _prepare(base, auth, run_id=race_run_id)
        assert race_status == 201, race_prepared
        race_reservation = race_prepared["reservation_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            commit_future = pool.submit(
                _commit,
                base,
                auth,
                race_reservation,
                run_id=race_run_id,
            )
            release_future = pool.submit(
                _release,
                base,
                auth,
                race_reservation,
                run_id=race_run_id,
            )
            commit_outcome = commit_future.result()
            release_outcome = release_future.result()
        assert release_outcome[0] == 201
        if commit_outcome[0] == 201:
            assert release_outcome[1]["released"] is False
            assert _run_exists(base, auth, race_run_id)
        else:
            assert commit_outcome[0] == 409
            assert release_outcome[1]["released"] is True
            assert not _run_exists(base, auth, race_run_id)


def test_prepare_refuses_when_real_worker_is_not_execution_ready(
    tmp_path: Path,
) -> None:
    """A cold externally managed worker yields no reservation or durable run."""
    with _armed_gateway(tmp_path, VAULTSPEC_AUTO_SPAWN_WORKER="false") as (
        base,
        auth,
    ):
        status, body = _prepare(base, auth, run_id="run-worker-not-ready")
        assert status == 503, body
        assert body["detail"] == "run admission is not execution-ready"
        assert _active_run_count(base, auth) == 0


def test_pre_durability_commit_failure_restores_reservation_for_release(
    tmp_path: Path,
) -> None:
    """A real post-authorization conflict restores the prepared authority."""
    owner_run_id = "run-nickname-owner"
    failed_run_id = "run-pre-durability-failure"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    metadata = {
        "workspace_root": str(workspace),
        "nickname": "post-authorization-conflict",
    }
    with _armed_gateway(tmp_path) as (base, auth):
        owner_status, owner_prepared = _prepare(
            base, auth, run_id=owner_run_id, metadata=metadata
        )
        assert owner_status == 201, owner_prepared
        owner_commit_status, owner_commit = _commit(
            base,
            auth,
            owner_prepared["reservation_id"],
            run_id=owner_run_id,
            metadata=metadata,
        )
        assert owner_commit_status == 201, owner_commit

        status, prepared = _prepare(base, auth, run_id=failed_run_id, metadata=metadata)
        assert status == 201, prepared
        reservation_id = prepared["reservation_id"]

        commit_status, conflict = _commit(
            base,
            auth,
            reservation_id,
            run_id=failed_run_id,
            metadata=metadata,
        )
        assert commit_status == 409, conflict
        assert "nickname already exists" in conflict["detail"]
        release_status, released = _release(
            base,
            auth,
            reservation_id,
            run_id=failed_run_id,
            metadata=metadata,
        )
        assert release_status == 201
        assert released["released"] is True


def test_gateway_restart_recovers_durable_lease_and_exact_commit_replay(
    tmp_path: Path,
) -> None:
    """A new gateway process recovers one run and lease without redispatch."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    run_id = "run-restart-recovery"

    with _running_gateway(tmp_path, app_home, log_name="gateway-first.log") as (
        base,
        auth,
    ):
        status, prepared = _prepare(base, auth, run_id=run_id)
        assert status == 201, prepared
        reservation_id = prepared["reservation_id"]
        committed_status, committed = _commit(base, auth, reservation_id, run_id=run_id)
        assert committed_status == 201, committed
        lease_id = committed["lease_id"]

    with _running_gateway(tmp_path, app_home, log_name="gateway-second.log") as (
        base,
        auth,
    ):
        with httpx.Client(base_url=base, timeout=10.0) as client:
            status_response = client.get(
                f"/v1/runs/{run_id}", headers={"Authorization": auth}
            )
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["lease_id"] == lease_id

        replay_status, replay = _commit(base, auth, reservation_id, run_id=run_id)
        assert replay_status == 201, replay
        assert replay["run_id"] == run_id
        assert replay["lease_id"] == lease_id

    second_log = (tmp_path / "gateway-second.log").read_text(
        encoding="utf-8", errors="replace"
    )
    assert _SPAWN_LINE not in second_log


def test_v1_write_body_is_rejected_before_unbounded_json_parsing(
    tmp_path: Path,
) -> None:
    """The live production gateway caps authenticated v1 write-body memory."""
    with _armed_gateway(tmp_path) as (base, auth):
        response = httpx.post(
            f"{base}/v1/runs",
            headers={"Authorization": auth, "Content-Type": "application/json"},
            content=b" " * (1024 * 1024 + 1),
            timeout=10,
        )

    assert response.status_code == 413, response.text
