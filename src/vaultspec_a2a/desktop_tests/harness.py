"""Real-process harness for installed desktop capsule artifact gates (W05.P13).

Install strategy
----------------
The full transport capsule build (S13) requires downloading CPython (~25 MB)
and Node.js (~20 MB) archives and is the province of the CI target-build legs
(S76-S80).  This harness assembles the installed layout from the real project
wheel and its locked base Python closure — the same package inputs the dashboard
activates after unpacking a transport capsule — which is the correct installed-
capsule boundary for the S73-S75 lifecycle gates.  Every consuming test file
documents this choice explicitly; the transport-capsule generation format and
its source-free verification remain the province of
``test_build_desktop_capsule.py`` and ``test_verify_desktop_capsule.py``.

Relocation model
----------------
A Python virtual environment on Windows cannot be naively moved to a new path
because the interpreter launcher and scripts embed absolute paths.  ``relocate``
therefore reinstalls from the cached wheel and pylock under ``UV_OFFLINE=1``,
which proves the closed package inventory is self-contained and resident in the
uv cache after the first install.  This models the dashboard activating a new
runtime generation at a different path; state in the app home is unaffected.

Adoption policy
---------------
This harness does NOT extract shared boilerplate from existing green W01-W04
gates.  Those tests are stable and refactoring them would risk regressions.
The harness supplies building blocks consumed exclusively by the new S73-S75
tests.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import httpx

from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.transaction import package_migration_range

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_MODULE: Final = "vaultspec_a2a.cli.main"
_PRESET: Final = "mock-success-single"
_REQUIRED_ROLE: Final = "mock-coder-success"
_SPAWN_LINE: Final = "Auto-spawning worker on port"

# Inline gateway script: starts the real production lifespan over a loopback
# socket with INFO logging so the one-shot spawn line is observable.  Identical
# to the pattern used by test_lazy_worker and test_run_admission.
GATEWAY_SCRIPT: Final = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""


@dataclass(frozen=True)
class InstalledCapsule:
    """An isolated Python environment with the desktop closure and wheel installed.

    Represents the installed-package form of one desktop capsule generation.
    ``wheel`` and ``pylock`` are retained so the capsule can be reinstalled at
    a new ``install_root`` (relocation) without a network fetch.
    """

    python: Path
    scripts_dir: Path
    install_root: Path
    wheel: Path
    pylock: Path


def _env_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _scripts_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def clean_env() -> dict[str, str]:
    """Return a process environment with virtual-environment isolation vars stripped."""
    env = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        env.pop(name, None)
    env["NO_COLOR"] = "1"
    env["UV_NO_PROGRESS"] = "1"
    return env


def offline_env() -> dict[str, str]:
    """Return a clean environment with network access blocked via an invalid proxy.

    Applied to child processes that must not reach the network after installation,
    proving the desktop closure is self-contained at runtime.  Port 0 is never
    bound, so any attempt to reach http_proxy or https_proxy immediately fails.
    """
    env = clean_env()
    # Port 0 is never bound; any proxy attempt fails immediately.
    _invalid_proxy = "http://127.0.0.1:0"
    env["http_proxy"] = _invalid_proxy
    env["https_proxy"] = _invalid_proxy
    env["HTTP_PROXY"] = _invalid_proxy
    env["HTTPS_PROXY"] = _invalid_proxy
    env["no_proxy"] = ""
    return env


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env if env is not None else clean_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise AssertionError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _install_into(
    venv: Path,
    pylock: Path,
    wheel: Path,
    uv: str,
    *,
    env: dict[str, str],
) -> Path:
    """Create a venv and install the closed lock + wheel; return the python path."""
    sandbox = venv.parent
    _run([uv, "venv", "--python", sys.executable, str(venv)], cwd=sandbox, env=env)
    python = _env_python(venv)
    assert python.is_file(), python
    _run(
        [uv, "pip", "install", "--python", str(python), "-r", str(pylock)],
        cwd=sandbox,
        env=env,
    )
    _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        cwd=sandbox,
        env=env,
    )
    _run([uv, "pip", "check", "--python", str(python)], cwd=sandbox, env=env)
    return python


def build_and_install(
    sandbox: Path,
    *,
    project_root: Path = _PROJECT_ROOT,
) -> InstalledCapsule:
    """Build the project wheel and install it with the locked base closure.

    Produces an ``InstalledCapsule`` whose ``wheel`` and ``pylock`` are retained
    for offline relocation without a second network fetch.
    """
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for the installed-capsule harness"

    dist_dir = sandbox / "dist"
    dist_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(dist_dir), "--no-sources"],
        cwd=project_root,
    )
    wheels = list(dist_dir.glob("vaultspec_a2a-*.whl"))
    assert len(wheels) == 1, wheels
    wheel = wheels[0]

    pylock = sandbox / "pylock.base.toml"
    _run(
        [
            uv,
            "export",
            "--format",
            "pylock.toml",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(pylock),
        ],
        cwd=project_root,
    )

    env = clean_env()
    venv = sandbox / "venv"
    python = _install_into(venv, pylock, wheel, uv, env=env)

    return InstalledCapsule(
        python=python,
        scripts_dir=_scripts_dir(venv),
        install_root=venv,
        wheel=wheel,
        pylock=pylock,
    )


def relocate(capsule: InstalledCapsule, new_root: Path) -> InstalledCapsule:
    """Reinstall the capsule at *new_root* from cached inputs without a network fetch.

    Models the dashboard activating a new runtime generation at a different path
    while mutable state remains in the app home.  ``UV_OFFLINE=1`` enforces that
    no package is fetched from the network; every required package must already
    reside in the uv cache from the first ``build_and_install`` call.
    """
    uv = shutil.which("uv")
    assert uv is not None

    env = clean_env()
    env["UV_OFFLINE"] = "1"

    venv = new_root / "venv"
    python = _install_into(venv, capsule.pylock, capsule.wheel, uv, env=env)

    return InstalledCapsule(
        python=python,
        scripts_dir=_scripts_dir(venv),
        install_root=venv,
        wheel=capsule.wheel,
        pylock=capsule.pylock,
    )


def free_port() -> int:
    """Return an unused loopback port (no long-lived reservation)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_listening(port: int, *, timeout: float = 0.5) -> bool:
    """Return whether a real TCP connection to the loopback port succeeds."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def seed_credentials(app_home: Path, prefix: str = "") -> tuple[str, str]:
    """Write dashboard-created attach and ownership credential files.

    Returns ``(attach_secret, ownership_secret)``.  The caller uses these to
    authenticate HTTP requests against the booted gateway.
    """
    tag = prefix or app_home.name[:16]
    attach = f"attach-credential-{tag}-1234567890abcdef"
    ownership = f"ownership-capability-{tag}-fedcba0987654321"

    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, attach),
        (OWNERSHIP_CAPABILITY_NAME, ownership),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)
    return attach, ownership


def write_migration_descriptor(
    path: Path,
    app_home: Path,
    txn_id: str,
    *,
    digest: str = "a" * 64,
    **overrides: object,
) -> Path:
    """Write a one-time migration descriptor targeting *app_home*."""
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    document: dict[str, object] = {
        "descriptor_version": "1",
        "transaction_id": txn_id,
        "app_home": str(app_home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": digest, "component_version": "4.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    document.update(overrides)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def seat_valid_database(
    python: Path,
    app_home: Path,
    descriptor: Path,
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Seat a valid desktop database by running ``desktop-migrate`` from *python*."""
    command = [
        str(python),
        "-m",
        _MODULE,
        "desktop-migrate",
        "--descriptor",
        str(descriptor),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "succeeded", payload
    assert derive_state_paths(app_home).database_path.is_file()


def await_gateway_health(base: str, *, timeout: float = 40.0) -> None:
    """Wait until the gateway's liveness endpoint answers 200."""
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(f"gateway liveness never came up ({last})")


def gateway_env(
    app_home: Path,
    gateway_port: int,
    worker_port: int,
    *,
    auto_spawn: bool = True,
) -> dict[str, str]:
    """Return an environment dict suitable for booting an armed desktop gateway.

    Derived from clean_env() (venv isolation vars stripped) rather than raw
    os.environ, so installed-capsule tests cannot inherit the development
    VIRTUAL_ENV or UV_PROJECT_ENVIRONMENT and accidentally resolve imports
    from the dev tree instead of the installed venv.
    """
    env = clean_env()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(gateway_port)
    env["VAULTSPEC_WORKER_PORT"] = str(worker_port)
    env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "true" if auto_spawn else "false"
    env["VAULTSPEC_REPAIR_ON_STARTUP"] = "false"
    return env


# Content of the mock-success-single team preset.  This preset is deliberately
# excluded from the product wheel (it is a test-only artifact); the workspace-
# override seam documented in team_config.py is the supported mechanism for
# supplying workspace-local presets to a running gateway.  Seeding it here lets
# the installed-capsule service gates prove the full run-start path without
# requiring the external ACP provider or the Claude CLI (which is not
# installable offline).  The preset is disclosed as the mock seam in every
# test module that depends on it.
_MOCK_SUCCESS_SINGLE_TOML: Final = """\
[team]
id           = "mock-success-single"
display_name = "Mock Success Single"
description  = "A single coder team that concludes work successfully."

[team.defaults]
provider   = "mock"
capability = "mid"

[team.topology]
type  = "pipeline"
order = ["mock-coder-success"]

[team.permissions]
auto_approve = true

[team.persona]
directive = "Simulate single agent success."

[team.graph]
step_timeout_seconds = 60
recursion_limit      = 10

[[team.workers]]
agent_id = "mock-coder-success"

[team.workers.defaults]
provider   = "mock"
capability = "mid"
"""


_MOCK_CODER_SUCCESS_TOML: Final = """\
[agent]
id           = "mock-coder-success"
display_name = "Mock Coder Success"
role         = "coder"
description  = "Mock coder agent that simulates a successful task completion."

[agent.persona]
system_prompt = "You are a mock coder. Emit your programmed sequence."

[agent.model]
provider   = "mock"
capability = "mid"

[agent.capabilities]
filesystem_read  = true
filesystem_write = true
terminal         = true

[agent.permissions]
require_approval_for = []
"""


def seed_workspace_preset(workspace: Path) -> Path:
    """Write mock-success-single team and mock-coder-success agent TOMLs.

    Both the team and its agent config are excluded from the product wheel.
    This function seeds them into workspace-override directories using the
    documented precedence seam from team_config.py:

        {workspace}/.vaultspec/teams/{team_id}.toml   (team override)
        {workspace}/.vaultspec/agents/{agent_id}.toml (agent override)

    Returns the workspace root so callers can pass it as the ``workspace_root``
    field in run-start ``metadata``.
    """
    vaultspec_dir = workspace / ".vaultspec"
    teams_dir = vaultspec_dir / "teams"
    agents_dir = vaultspec_dir / "agents"
    teams_dir.mkdir(parents=True, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    (teams_dir / "mock-success-single.toml").write_text(
        _MOCK_SUCCESS_SINGLE_TOML, encoding="utf-8"
    )
    (agents_dir / "mock-coder-success.toml").write_text(
        _MOCK_CODER_SUCCESS_TOML, encoding="utf-8"
    )
    return workspace
