"""Certify the caller-owned standalone MCP adapter from a clean installed capsule.

The gate builds the real wheel, installs the locked base closure plus the wheel
into a clean interpreter, and exercises the shipped ``vaultspec-a2a-mcp`` console
script from that installed environment. It proves the adapter is a caller-owned
process: the test starts it directly, it binds its own loopback port, and the test
stops it - no desktop gateway launches or adopts it. The desktop lifecycle is
never started in this gate; the adapter runs entirely on its own.

No mock, monkeypatch, stub, skip, or expected failure is used. The build-and-
install cases are marked ``service`` (consistent with the other installed-capsule
gates) because they run ``uv build`` and provision a clean environment.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
_MCP_SCRIPT: Final = "vaultspec-a2a-mcp"


@dataclass(frozen=True)
class InstalledCapsule:
    """A clean interpreter with the desktop base closure and wheel installed."""

    python: Path
    sandbox: Path
    scripts_dir: Path


def _clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["UV_NO_PROGRESS"] = "1"
    return environment


def _run(command: list[str], *, cwd: Path, timeout: int = 600) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=_clean_environment(),
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


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _scripts_dir(environment: Path) -> Path:
    return environment / ("Scripts" if os.name == "nt" else "bin")


def _mcp_script(capsule: InstalledCapsule) -> Path:
    """Return the installed ``vaultspec-a2a-mcp`` console script path."""
    suffix = ".exe" if os.name == "nt" else ""
    return capsule.scripts_dir / f"{_MCP_SCRIPT}{suffix}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_listening(port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def installed_capsule(tmp_path_factory: pytest.TempPathFactory) -> InstalledCapsule:
    """Build the wheel and install the base closure plus wheel into a clean venv."""
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to certify the standalone MCP entrypoint"

    sandbox = tmp_path_factory.mktemp("desktop-standalone-mcp")
    distribution_dir = sandbox / "dist"
    distribution_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(distribution_dir), "--no-sources"],
        cwd=_PROJECT_ROOT,
    )
    wheels = list(distribution_dir.glob("vaultspec_a2a-*.whl"))
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
        cwd=_PROJECT_ROOT,
    )

    environment = sandbox / "venv"
    _run([uv, "venv", "--python", sys.executable, str(environment)], cwd=sandbox)
    python = _environment_python(environment)
    assert python.is_file(), python

    _run(
        [uv, "pip", "install", "--python", str(python), "-r", str(pylock)],
        cwd=sandbox,
    )
    _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        cwd=sandbox,
    )
    _run([uv, "pip", "check", "--python", str(python)], cwd=sandbox)

    return InstalledCapsule(
        python=python, sandbox=sandbox, scripts_dir=_scripts_dir(environment)
    )


@pytest.mark.service
def test_installed_capsule_ships_caller_owned_mcp_entrypoint(
    installed_capsule: InstalledCapsule,
) -> None:
    """The clean capsule ships the standalone MCP console script, caller-invokable."""
    script = _mcp_script(installed_capsule)
    assert script.is_file(), f"missing installed console script: {script}"

    result = subprocess.run(
        [str(script), "--help"],
        cwd=installed_capsule.sandbox,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    # The help text describes the transport options a caller drives it with.
    assert "--transport" in result.stdout
    assert "stdio" in result.stdout and "streamable-http" in result.stdout


@pytest.mark.service
def test_caller_owned_standalone_mcp_starts_and_stops(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """The caller starts and stops the standalone adapter; no gateway is involved.

    The test launches the shipped console script directly - it is the process's
    only owner - waits for it to bind its own loopback port, and then terminates
    it. No desktop gateway is created in this test, so the adapter is proven to run
    and be reaped entirely under caller ownership, never launched or adopted by the
    desktop lifecycle.
    """
    port = _free_port()
    log_path = tmp_path / "mcp.log"
    env = _clean_environment()
    # A bogus gateway URL proves the adapter binds without a live gateway: it
    # connects to the gateway lazily on a tool call, not at startup.
    env["VAULTSPEC_GATEWAY_URL"] = "http://127.0.0.1:1"

    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [
            str(_mcp_script(installed_capsule)),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=installed_capsule.sandbox,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        # --- Started: the caller-owned process binds its own loopback port. ---
        deadline = time.monotonic() + 40.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log_handle.flush()
                raise AssertionError(
                    "standalone MCP exited during startup:\n"
                    + log_path.read_text(encoding="utf-8", errors="replace")
                )
            if _port_listening(port):
                break
            time.sleep(0.2)
        else:
            raise AssertionError(
                "standalone MCP never bound its port:\n"
                + log_path.read_text(encoding="utf-8", errors="replace")
            )

        # The adapter is alive and owned by this test (the caller), not a gateway.
        assert proc.poll() is None
        assert _port_listening(port)
    finally:
        # --- Stopped: the caller reaps it; it obeys its owner. ---
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
            proc.kill()
            proc.wait(timeout=20)
        log_handle.close()

    # After the caller stops it, the port is released - the adapter's lifecycle
    # was entirely the caller's to end.
    release_deadline = time.monotonic() + 10.0
    while time.monotonic() < release_deadline and _port_listening(port):
        time.sleep(0.2)
    assert not _port_listening(port), "the stopped adapter must release its port"
