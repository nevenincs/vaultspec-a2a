"""The production dashboard engine, run beside A2A for cross-repository proofs.

The dashboard is a separate repository, so a proof that crosses into it runs the
operator-declared engine binary (``VAULTSPEC_A2A_ENGINE_SERVE_CMD``) against a
provisioned engine workspace and an A2A it discovers through a service record.
Every such proof needs the same workspace, the same discovery seat and the same
engine lifecycle, so they are built here once rather than per proof.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from http import HTTPStatus
from importlib.resources import files
from typing import TYPE_CHECKING

import httpx

from ..lifecycle.discovery import write_service_json
from ..testing import (
    DEFAULT_ATTACH_CREDENTIAL,
    LivenessWatch,
    ProgressDeadline,
    inherited_environment,
    json_object,
    wait_for,
)
from ..utils import ProcessContainment, bearer_header, reap_contained, spawn_contained

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

__all__ = ["dashboard_engine", "provision_workspace"]


def provision_workspace(workspace: Path) -> None:
    """Create a committed vaultspec workspace the engine can scope a run to."""
    workspace.mkdir()
    core = shutil.which("vaultspec-core")
    assert core is not None, "vaultspec-core executable is required"
    install = subprocess.run(
        [core, "install", "--target", str(workspace)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert install.returncode == 0, install.stderr
    plan = workspace / ".vault" / "plan" / "cross-repo-proof.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "---\ntags:\n  - '#plan'\ndate: '2026-07-20'\n---\n\n# proof\n",
        encoding="utf-8",
    )
    teams = workspace / ".vaultspec" / "teams"
    teams.mkdir(parents=True, exist_ok=True)
    bundled_solo = (
        files("vaultspec_a2a.team.presets.teams")
        .joinpath("vaultspec-solo-coder.toml")
        .read_text(encoding="utf-8")
    )
    (teams / "vaultspec-solo-coder.toml").write_text(
        bundled_solo,
        encoding="utf-8",
    )
    git = shutil.which("git")
    assert git is not None, "git executable is required"
    env = inherited_environment(
        {
            "GIT_AUTHOR_NAME": "cross-repo-proof",
            "GIT_AUTHOR_EMAIL": "proof@vaultspec.test",
            "GIT_COMMITTER_NAME": "cross-repo-proof",
            "GIT_COMMITTER_EMAIL": "proof@vaultspec.test",
        }
    )
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["commit", "-qm", "cross-repo fixture"],
    ):
        result = subprocess.run(
            [git, *args],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr


def _engine_command(port: int, workspace: Path) -> list[str]:
    """The declared dashboard serve command, rendered by production.

    Rendering goes through ``engine_command``, the launcher's own renderer, so
    this proof launches the engine the way the product does - host-aware quoting,
    substitution per token - rather than through a second reading of the same
    template that could drift from it.

    What stays here is the prerequisite's own shape check. Only reached once the
    ``dashboard-engine`` prerequisite has been asserted present, so a blank
    template is impossible and every remaining check is a real defect in a
    command the caller did supply.
    """
    from ..lifecycle.engine_serve import engine_command

    command = engine_command(port, str(workspace))
    assert command and os.path.isabs(command[0]), (
        "engine command must use an absolute binary"
    )
    assert os.path.isfile(command[0]), f"engine binary is missing: {command[0]}"
    assert "serve" in command and "--no-seat" in command, (
        "engine command must be a non-seating serve invocation"
    )
    return command


def _wait_for_engine(
    workspace: Path, base_url: str, process: subprocess.Popen[bytes]
) -> str:
    """Return the engine's service token once it answers ``/status`` with it."""
    discovery = workspace / ".vault" / "data" / "engine-data" / "service.json"
    last_error = "not started"

    def _ready() -> str | None:
        nonlocal last_error
        try:
            record = json_object(
                json.loads(discovery.read_text(encoding="utf-8")),
                at="engine discovery record",
            )
            token = record.get("service_token")
            if not isinstance(token, str):
                raise KeyError("service_token")
            response = httpx.get(
                f"{base_url}/status",
                headers=bearer_header(token),
                timeout=2,
            )
            if response.status_code == HTTPStatus.OK:
                return token
            last_error = response.text
        except (OSError, KeyError, json.JSONDecodeError, httpx.HTTPError) as exc:
            last_error = repr(exc)
        return None

    def _exited() -> str | None:
        if process.poll() is None:
            return None
        return (
            f"exited with code {process.returncode} during startup; "
            f"last readiness error: {last_error}"
        )

    return wait_for(
        _ready,
        deadline=ProgressDeadline(
            idle_window_s=40.0,
            watches=(LivenessWatch(label="dashboard engine", verdict=_exited),),
        ),
        interval_s=0.1,
        stalled=lambda: f"dashboard engine did not become ready: {last_error}",
    )


def _shutdown_engine(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    base_url: str,
    token: str,
) -> None:
    try:
        response = httpx.post(
            f"{base_url}/shutdown",
            headers=bearer_header(token),
            json={},
            timeout=5,
        )
        assert response.status_code == HTTPStatus.OK, response.text
        process.wait(timeout=15)
    finally:
        _force_engine_tree_exit(process, containment)


def _force_engine_tree_exit(
    process: subprocess.Popen[bytes], containment: ProcessContainment
) -> None:
    """Boundedly terminate the OS-owned engine containment and reap its root."""
    if not reap_contained(process, containment, term_timeout=5.0, kill_timeout=5.0):
        raise AssertionError(f"engine process containment {process.pid} did not empty")


@contextmanager
def dashboard_engine(
    tmp_path: Path,
    *,
    workspace: Path,
    engine_port: int,
    engine_log: Path,
    a2a_port: int,
) -> Generator[str]:
    """Run the declared production engine against the A2A listening on *a2a_port*.

    The engine discovers A2A through a service record naming *a2a_port* - the
    gateway itself, or a relay standing in front of it - and runs inside its own
    OS containment with its output in *engine_log*. Yields the engine's service
    token once it is ready. On exit the engine is shut down through its own verb,
    or its whole tree is reaped when it never became ready.
    """
    engine_base = f"http://127.0.0.1:{engine_port}"
    discovery_home = tmp_path / "a2a-discovery"
    write_service_json(
        discovery_home / "service.json",
        port=a2a_port,
        pid=os.getpid(),
        service_token=DEFAULT_ATTACH_CREDENTIAL,
    )
    environment = inherited_environment(
        {
            "VAULTSPEC_A2A_DESKTOP_APP_HOME": None,
            "VAULTSPEC_A2A_HOME": str(discovery_home),
            "VAULTSPEC_APP_HOME": str(tmp_path / "dashboard-product-home"),
        }
    )
    with engine_log.open("wb") as output:
        containment = ProcessContainment.create()
        process: subprocess.Popen[bytes] | None = None
        token: str | None = None
        try:
            process = spawn_contained(
                _engine_command(engine_port, workspace),
                containment,
                cwd=workspace,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            token = _wait_for_engine(workspace, engine_base, process)
            yield token
        finally:
            if process is None:
                containment.close()
            elif token is not None:
                _shutdown_engine(process, containment, engine_base, token)
            else:
                _force_engine_tree_exit(process, containment)
