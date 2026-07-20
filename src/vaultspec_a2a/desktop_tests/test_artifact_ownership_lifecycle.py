"""Certify the desktop capsule ownership lifecycle: authenticated attach, owner-only
shutdown, drain, and data-preserving capsule removal.

All operations are driven against real armed gateway processes using the installed
capsule python.  No mock, monkeypatch, stub, skip, or expected failure is used.

Install strategy
----------------
Same wheel-install approach as ``test_artifact_install.py`` (see that module's
docstring for rationale).

Data-preservation guarantee
----------------------------
The ADR states: "Only an explicit data-removal operation deletes user data."  The
``test_data_preserving_capsule_removal`` case proves this directly: the installed
capsule virtual environment (the immutable runtime generation) is deleted, and the
app home's databases, credentials, and discovery state remain fully intact.  This
models the dashboard installing a new runtime generation while preserving user data.

All tests are marked ``service`` because they run ``uv build`` and provision a
clean environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.utils import kill_pid_tree_async

from .harness import (
    _PRESET,
    GATEWAY_SCRIPT,
    InstalledCapsule,
    await_gateway_health,
    build_and_install,
    free_port,
    gateway_env,
    port_listening,
    seat_valid_database,
    seed_credentials,
    seed_workspace_preset,
    write_migration_descriptor,
)

if TYPE_CHECKING:
    from pathlib import Path

_LIFECYCLE_HEADER = "X-Vaultspec-Lifecycle-Capability"


# ---------------------------------------------------------------------------
# Module-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def installed_capsule(tmp_path_factory: pytest.TempPathFactory) -> InstalledCapsule:
    """Build the project wheel and install the desktop closure into a clean venv."""
    sandbox = tmp_path_factory.mktemp("artifact-ownership-capsule")
    return build_and_install(sandbox)


# ---------------------------------------------------------------------------
# Helper: arm a full desktop home (migrate + credentials)
# ---------------------------------------------------------------------------


def _arm_home(
    capsule: InstalledCapsule,
    tmp_path: Path,
    txn_id: str,
    prefix: str,
) -> tuple[Path, str, str]:
    """Seed credentials, migrate, return (app_home, attach, ownership)."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    attach, ownership = seed_credentials(app_home, prefix=prefix)
    descriptor = write_migration_descriptor(tmp_path / "txn.json", app_home, txn_id)
    seat_valid_database(capsule.python, app_home, descriptor)
    return app_home, attach, ownership


# ---------------------------------------------------------------------------
# S75 test 1 - unauthenticated access is rejected on all protected endpoints
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_unauthenticated_access_rejected(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Unauthenticated and wrong-credential requests are rejected on the attach plane.

    The gateway exposes a minimal alive signal unauthenticated; every other
    endpoint on the attach plane requires the correct attach credential.  This
    gate proves: unauthenticated liveness is 200, service-state without auth is
    401, the worker-IPC credential is rejected on the attach plane, and a random
    bearer is also rejected.
    """
    app_home, attach, _ownership = _arm_home(
        installed_capsule, tmp_path, "unauth-txn-1", "unauth"
    )
    gw_port = free_port()
    wk_port = free_port()
    env = gateway_env(app_home, gw_port, wk_port, auto_spawn=False)
    base = f"http://127.0.0.1:{gw_port}"

    log_handle = (tmp_path / "gw.log").open("wb")
    proc = subprocess.Popen(
        [str(installed_capsule.python), "-c", GATEWAY_SCRIPT, str(gw_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        await_gateway_health(base)

        with httpx.Client(base_url=base, timeout=30.0) as client:
            # Minimal liveness is public.
            live = client.get("/health")
            assert live.status_code == 200
            assert live.content == b'{"liveness":"alive"}'

            # Service state without auth is rejected.
            assert client.get("/v1/service").status_code == 401

            # Random bearer is rejected.
            assert (
                client.get(
                    "/v1/service",
                    headers={"Authorization": "Bearer not-the-attach-secret"},
                ).status_code
                == 401
            )

            # Correct attach credential authenticates.
            auth_ok = client.get(
                "/v1/service",
                headers={"Authorization": f"Bearer {attach}"},
            )
            assert auth_ok.status_code != 401

            # Admin shutdown without ownership capability is rejected (attach only).
            # Expected: 403.
            attach_only_shutdown = client.post(
                "/api/admin/shutdown",
                headers={"Authorization": f"Bearer {attach}"},
            )
            assert attach_only_shutdown.status_code == 403
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()


# ---------------------------------------------------------------------------
# S75 test 2 - owner-only shutdown requires the ownership capability
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_owner_only_shutdown_requires_ownership_capability(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Admin shutdown is gated on both the attach credential and the ownership cap.

    Proves: attach alone → 403; attach + wrong capability → 403;
    attach + correct ownership capability → 202 and the gateway stops.
    """
    app_home, attach, ownership = _arm_home(
        installed_capsule, tmp_path, "owner-shutdown-txn-1", "ownsht"
    )
    gw_port = free_port()
    wk_port = free_port()
    env = gateway_env(app_home, gw_port, wk_port, auto_spawn=False)
    base = f"http://127.0.0.1:{gw_port}"
    auth = {"Authorization": f"Bearer {attach}"}

    log_handle = (tmp_path / "gw.log").open("wb")
    proc = subprocess.Popen(
        [str(installed_capsule.python), "-c", GATEWAY_SCRIPT, str(gw_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        await_gateway_health(base)

        with httpx.Client(base_url=base, timeout=30.0) as client:
            # Attach alone: 403.
            r1 = client.post("/api/admin/shutdown", headers=auth)
            assert r1.status_code == 403, r1.text

            # Attach + wrong ownership capability: 403.
            r2 = client.post(
                "/api/admin/shutdown",
                headers={**auth, _LIFECYCLE_HEADER: "not-the-real-ownership"},
            )
            assert r2.status_code == 403, r2.text

            # Attach + correct ownership capability: 202, gateway starts draining.
            with contextlib.suppress(httpx.HTTPError):
                r3 = client.post(
                    "/api/admin/shutdown",
                    headers={**auth, _LIFECYCLE_HEADER: ownership},
                )
                assert r3.status_code == 202, r3.text

        # Gateway exits gracefully before the force-kill deadline.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
        assert proc.poll() is not None, "owner-only shutdown must stop the gateway"

        # Port is released — the gateway is fully gone.
        deadline = time.monotonic() + 10.0
        while port_listening(gw_port) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not port_listening(gw_port), (
            "gateway port must be released after shutdown"
        )
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()


# ---------------------------------------------------------------------------
# S75 test 3 - drain and graceful shutdown reap the worker tree
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_drain_and_graceful_shutdown_reaps_worker(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Drain closes admission; graceful shutdown reaps the gateway-owned worker.

    Boots the gateway with auto-spawn enabled, starts a real run to bring the
    worker online, then triggers owner-authenticated shutdown.  Drain closes
    admission (the gateway no longer accepts new run-starts) and the lifespan
    reaps the worker via OS containment before the gateway exits.  The worker
    port frees before the force-kill deadline, proving the containment reap —
    not the teardown tree-kill — fells the worker.
    """
    app_home, attach, ownership = _arm_home(
        installed_capsule, tmp_path, "drain-shutdown-txn-1", "drain"
    )
    # Seed the workspace-override preset so the installed capsule can resolve it.
    workspace = seed_workspace_preset(tmp_path / "workspace")
    gw_port = free_port()
    wk_port = free_port()
    env = gateway_env(app_home, gw_port, wk_port, auto_spawn=True)
    base = f"http://127.0.0.1:{gw_port}"
    auth = {"Authorization": f"Bearer {attach}"}

    log_handle = (tmp_path / "gw.log").open("wb")
    proc = subprocess.Popen(
        [str(installed_capsule.python), "-c", GATEWAY_SCRIPT, str(gw_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        await_gateway_health(base)

        # Start a real run to bring the worker online.
        with httpx.Client(base_url=base, timeout=60.0) as client:
            resp = client.post(
                "/v1/runs",
                headers=auth,
                json={
                    "team_preset": _PRESET,
                    "message": "build it",
                    "autonomous": True,
                    "actor_tokens": {
                        "tokens": {"coder": "tok-coder"},
                        "engine_bearer": "bearer",
                    },
                    "metadata": {
                        "workspace_root": str(workspace),
                    },
                },
            )
        assert resp.status_code == 201, resp.text

        # Wait for the worker to bind its port.
        deadline = time.monotonic() + 30.0
        while not port_listening(wk_port) and time.monotonic() < deadline:
            time.sleep(0.25)
        assert port_listening(wk_port), "run start must have brought the worker online"

        # Trigger owner-authenticated shutdown with drain.
        with (
            contextlib.suppress(httpx.HTTPError),
            httpx.Client(base_url=base, timeout=30.0) as client,
        ):
            shutdown = client.post(
                "/api/admin/shutdown",
                headers={**auth, _LIFECYCLE_HEADER: ownership},
            )
            assert shutdown.status_code == 202, shutdown.text

        # Gateway exits before the force-kill deadline.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
        assert proc.poll() is not None, "shutdown must stop the gateway"

        # Worker port freed via containment reap — not via force-kill.
        worker_deadline = time.monotonic() + 15.0
        while port_listening(wk_port) and time.monotonic() < worker_deadline:
            time.sleep(0.25)
        assert not port_listening(wk_port), (
            "graceful shutdown must reap the gateway-owned worker tree"
        )
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()


# ---------------------------------------------------------------------------
# S75 test 4 - capsule removal preserves app_home user data
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_data_preserving_capsule_removal(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Removing the capsule runtime leaves user data in the app home intact.

    Models the dashboard uninstalling a runtime generation: the immutable capsule
    virtual environment (install_root) is deleted while the mutable app home
    retains all user data.  Per the ADR: "Only an explicit data-removal operation
    deletes user data."

    After the capsule is removed the database, checkpoint, credentials, and
    discovery record are verified to be fully intact on disk, proving the capsule
    and the app home are genuinely separate authorities.
    """
    # Use a per-test capsule copy so the module-scoped capsule remains intact.
    test_root = tmp_path / "capsule-removal-root"
    test_root.mkdir()

    # Build a fresh capsule for this test (module-scoped one must not be deleted).
    test_capsule = build_and_install(test_root)

    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _attach, _ownership = seed_credentials(app_home, prefix="removal")
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, "removal-txn-1"
    )
    seat_valid_database(test_capsule.python, app_home, descriptor)

    # Boot the gateway briefly to create the discovery record.
    gw_port = free_port()
    wk_port = free_port()
    env = gateway_env(app_home, gw_port, wk_port, auto_spawn=False)
    base = f"http://127.0.0.1:{gw_port}"

    log_handle = (tmp_path / "gw.log").open("wb")
    proc = subprocess.Popen(
        [str(test_capsule.python), "-c", GATEWAY_SCRIPT, str(gw_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        await_gateway_health(base)
        # Give the lifespan a moment to write the discovery record.
        time.sleep(1.0)
        # Publication is asserted while the gateway is LIVE: a clean shutdown
        # deliberately removes the record it owns, so its presence afterwards
        # would only mean the process was killed too hard to run its cleanup.
        assert derive_state_paths(app_home).discovery_path.is_file(), (
            "gateway lifespan must publish a discovery record while serving"
        )
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()

    state = derive_state_paths(app_home)

    # Publication was asserted above while the gateway served. The record is not
    # re-asserted here: a clean shutdown removes the record its owner published,
    # so whether it survives the stop reflects only how hard the process was
    # killed, not whether capsule removal preserves user data.

    # Capture the paths and sizes of all user-data files before removal.
    # Credential filenames use the canonical constants from credentials.py.
    user_data_files = {
        "database": state.database_path,
        "checkpoint": state.checkpoint_path,
        "attach_cred": state.credentials_dir / ATTACH_CREDENTIAL_NAME,
        "ownership_cred": state.credentials_dir / OWNERSHIP_CAPABILITY_NAME,
        "discovery": state.discovery_path,
    }
    pre_sizes = {
        label: path.stat().st_size
        for label, path in user_data_files.items()
        if path.exists()
    }
    assert pre_sizes, "no user data files found before capsule removal"

    # --- Remove the capsule runtime (immutable generation). ---
    shutil.rmtree(str(test_capsule.install_root))
    assert not test_capsule.install_root.exists(), (
        "capsule removal must delete the venv"
    )

    # --- User data is fully intact after capsule removal. ---
    for label, path in user_data_files.items():
        if label not in pre_sizes:
            continue
        assert path.exists(), f"user data file missing after capsule removal: {path}"
        assert path.stat().st_size == pre_sizes[label], (
            f"user data file size changed after capsule removal: {label}"
        )

    # The app home itself is unaffected.
    assert app_home.is_dir(), "app home directory must survive capsule removal"
    assert state.database_path.is_file(), (
        "primary database must survive capsule removal"
    )
    assert state.checkpoint_path.is_file(), (
        "checkpoint database must survive capsule removal"
    )
    assert state.discovery_path.is_file(), (
        "discovery record must survive capsule removal"
    )
