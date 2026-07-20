"""Certify the installed desktop capsule artifact: install, relocation, readiness,
lazy worker, and default execution from one real capsule.

Install strategy
----------------
The full transport capsule (S13) requires downloading CPython and Node.js
archives not available offline on this host.  These gates instead use the wheel-
install approach implemented by ``harness.build_and_install``: build the real
project wheel, export the locked base closure, and install both into a clean
virtual environment.  This produces the installed-package form of the desktop
capsule — the boundary the gateway, worker, and CLI commands actually consume —
and is documented here and in the step record.

Default ACP execution
---------------------
The external Claude CLI is not installable offline.  This gate follows the
established mock-success-single preset pattern used by every other gateway gate
(test_lazy_worker, test_run_admission, test_owned_process_tree, etc.): the
``mock-success-single`` team preset exercises the full run-start path including
worker boot, dispatch, and run creation without invoking the Claude CLI.  This
is the MOCK-provider-at-the-uninstalled-CLI-seam precedent referenced in S73.

All tests are marked ``service`` because they run ``uv build`` and provision a
clean environment.  No mock, monkeypatch, stub, skip, or expected failure is
used beyond the disclosed mock preset.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.utils import kill_pid_tree_async

from .harness import (
    _PRESET,
    _SPAWN_LINE,
    GATEWAY_SCRIPT,
    InstalledCapsule,
    await_gateway_health,
    build_and_install,
    free_port,
    gateway_env,
    port_listening,
    relocate,
    seat_valid_database,
    seed_credentials,
    seed_workspace_preset,
    write_migration_descriptor,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Module-scoped fixture: build and install the capsule once for the module.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def installed_capsule(tmp_path_factory: pytest.TempPathFactory) -> InstalledCapsule:
    """Build the project wheel and install the desktop closure into a clean venv."""
    sandbox = tmp_path_factory.mktemp("artifact-install-capsule")
    return build_and_install(sandbox)


# ---------------------------------------------------------------------------
# Helpers shared across the tests in this module
# ---------------------------------------------------------------------------


def _seat_app_home(
    capsule: InstalledCapsule,
    tmp_path: Path,
    txn_id: str,
) -> tuple[Path, str, str]:
    """Create and seat a fresh app home; return (app_home, attach, ownership)."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    attach, ownership = seed_credentials(app_home, prefix=txn_id[:16])
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, txn_id
    )
    seat_valid_database(capsule.python, app_home, descriptor)
    return app_home, attach, ownership


# ---------------------------------------------------------------------------
# S73 test 1 - clean offline install seats a valid database
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_offline_install_seats_valid_database(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """The installed capsule's desktop-migrate command seats a valid database.

    Drives the CLI via the installed python, proving migration works from the
    isolated environment without importing from the development tree.
    """
    import sqlite3

    from vaultspec_a2a.desktop.transaction import package_migration_range

    app_home = tmp_path / "app"
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, "install-offline-1"
    )
    seat_valid_database(installed_capsule.python, app_home, descriptor)

    state = derive_state_paths(app_home)
    head = package_migration_range().head

    version = (
        sqlite3.connect(str(state.database_path))
        .execute("SELECT version_num FROM alembic_version")
        .fetchone()
    )
    assert version is not None and version[0] == head
    assert state.checkpoint_path.is_file()

    # State paths derive from app_home, NOT from the capsule install path.
    assert not str(state.database_path).startswith(str(installed_capsule.install_root))


# ---------------------------------------------------------------------------
# S73 test 2 - relocation: new capsule path, same app home, same state
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_capsule_relocation_preserves_state_independence(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """A relocated capsule uses the same app home; state never lives in the capsule.

    Installs a second capsule at a new path (UV_OFFLINE=1, no network fetch),
    then proves both capsule instances can seat and read the same app home's
    database.  This models the dashboard activating a new runtime generation
    while user data remains in the app home.
    """

    app_home = tmp_path / "app"
    descriptor_a = write_migration_descriptor(
        tmp_path / "txn-a.json", app_home, "relocation-txn-a"
    )
    seat_valid_database(installed_capsule.python, app_home, descriptor_a)

    new_root = tmp_path / "capsule-b"
    new_root.mkdir()
    relocated = relocate(installed_capsule, new_root)

    # The relocated python can read the same database produced by the original
    # install - proving state lives in app_home, not in either capsule path.
    _db_repr = repr(str(derive_state_paths(app_home).database_path))
    _alembic_q = "SELECT version_num FROM alembic_version"
    result = subprocess.run(
        [
            str(relocated.python),
            "-c",
            (
                "import sqlite3, sys\n"
                f"conn = sqlite3.connect({_db_repr})\n"
                f"row = conn.execute('{_alembic_q}').fetchone()\n"
                "print(row[0])\n"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "relocated capsule must read the seated revision"

    # Neither capsule path contains the database.
    db = derive_state_paths(app_home).database_path
    assert not str(db).startswith(str(installed_capsule.install_root))
    assert not str(db).startswith(str(relocated.install_root))


# ---------------------------------------------------------------------------
# S73 test 3 - cold readiness from the installed capsule
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_cold_readiness_from_installed_capsule(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """An armed gateway (installed python) boots gateway-ready with a cold worker.

    Proves the installed package's production lifespan exposes the minimal alive
    signal unauthenticated and the full authenticated readiness facts (gateway-
    ready, worker cold, admission deferred) from the cold-to-execution ladder.
    """
    app_home, attach, _ = _seat_app_home(
        installed_capsule, tmp_path, "cold-readiness-txn-1"
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

        with httpx.Client(base_url=base, timeout=5.0) as client:
            # Unauthenticated liveness discloses only the minimal alive signal.
            live = client.get("/health")
            assert live.status_code == 200
            assert live.content == b'{"liveness":"alive"}'

            # Authenticated readiness carries identity and the cold ladder.
            auth = {"Authorization": f"Bearer {attach}"}
            ready = client.get("/health", headers=auth)
            assert ready.status_code == 200
            body = ready.json()
            assert body["profile"] == "desktop"
            assert body["liveness"] == "alive"
            assert body["gateway_readiness"] == "ready"
            assert body["worker_state"] == "cold"
            assert body["run_admission"] == "deferred"
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()


# ---------------------------------------------------------------------------
# S73 test 4 - lazy worker from the installed capsule
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_lazy_worker_from_installed_capsule(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Concurrent first demand creates one real worker; idle boot creates none.

    Proved through the installed capsule's python: the gateway is booted via the
    installed package so every code path - auth loading, worker spawner, run-start
    dispatch - runs from the installed environment.

    The mock-success-single preset is seeded into a workspace override directory
    and passed via run-start metadata.workspace_root, using the documented
    workspace-precedence seam (team_config.py discovery order), because the
    product wheel deliberately excludes mock presets.
    """
    app_home, attach, _ = _seat_app_home(
        installed_capsule, tmp_path, "lazy-worker-installed-txn-1"
    )
    workspace = seed_workspace_preset(tmp_path / "workspace")
    gw_port = free_port()
    wk_port = free_port()
    env = gateway_env(app_home, gw_port, wk_port, auto_spawn=True)
    base = f"http://127.0.0.1:{gw_port}"
    auth = {"Authorization": f"Bearer {attach}"}

    log_path = tmp_path / "gw.log"
    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [str(installed_capsule.python), "-c", GATEWAY_SCRIPT, str(gw_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        await_gateway_health(base)

        # --- Idle boot: worker port never listened, state is cold. ---
        time.sleep(1.0)
        assert not port_listening(wk_port), "idle boot must not start the worker"
        with httpx.Client(base_url=base, timeout=5.0) as client:
            assert client.get("/health", headers=auth).json()["worker_state"] == "cold"
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        assert _SPAWN_LINE not in log_text

        # --- Concurrent first demand: exactly one worker, one spawn line. ---
        def _start_run(_: Any) -> int:
            with httpx.Client(base_url=base, timeout=60.0) as client:
                return client.post(
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
                ).status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(_start_run, range(4)))
        assert statuses == [201, 201, 201, 201], statuses

        assert port_listening(wk_port), "first demand must start the worker"
        spawn_count = log_path.read_text(encoding="utf-8", errors="replace").count(
            _SPAWN_LINE
        )
        assert spawn_count == 1, f"expected one spawn, saw {spawn_count}"
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()


# ---------------------------------------------------------------------------
# S73 test 5 - default ACP execution via the mock-provider seam
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_default_acp_execution_mock_seam(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """A run executes from the installed capsule gateway via the mock-provider seam.

    The external Claude CLI is not installable offline; this test exercises the
    full run-start path (worker boot, dispatch, durable run creation) from the
    installed capsule's production code using the mock-success-single preset.
    The preset is not bundled in the product wheel; it is seeded into a workspace
    override directory and supplied via run-start metadata.workspace_root, using
    the documented workspace-precedence seam.  This is disclosed as the
    MOCK-provider-at-the-uninstalled-CLI-seam used by all installed-capsule gates.
    """
    app_home, attach, _ = _seat_app_home(
        installed_capsule, tmp_path, "acp-execution-mock-txn-1"
    )
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
        body = resp.json()
        assert body.get("run_id")

        # A durable run exists under the returned id.
        with httpx.Client(base_url=base, timeout=10.0) as client:
            status_resp = client.get(f"/v1/runs/{body['run_id']}", headers=auth)
        assert status_resp.status_code == 200, status_resp.text

        # The worker is now live.
        assert port_listening(wk_port), "run creation must have started the worker"
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()
