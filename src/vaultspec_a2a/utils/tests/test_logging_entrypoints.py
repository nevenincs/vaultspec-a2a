"""Regression protection for the entrypoint logging-lane wiring (P01.S05).

Real subprocesses and the real click group - no mocks. Two guarantees:
  1. The protocol lane keeps stdout a pure JSON-RPC channel (a WARNING rides stderr
     while stdout carries only the frame).
  2. Each entrypoint invokes ``configure_logging`` with its expected kind - proven by
     the observable lane it produces (service kinds materialize their named rotating
     file lane; the CLI group configures the cli lane; the stdio protocol entrypoint
     leaves stdout clean).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _clean_root_logger() -> Generator[None]:
    def _reset() -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    _reset()
    yield
    _reset()


def _write_child(tmp_path: Path, name: str, code: str) -> Path:
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    return path


def _run_child(
    child: Path,
    *,
    env_extra: dict[str, str],
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(child)],
        env=env,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )


def _has_log_json_on_stdout(stdout: str) -> bool:
    for line in stdout.splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict) and "level" in obj and "name" in obj:
            return True
    return False


# --- protocol lane stdout purity (contract) --------------------------------


def test_protocol_lane_keeps_stdout_pure_json_rpc(tmp_path: Path) -> None:
    child = _write_child(
        tmp_path,
        "proto_child.py",
        (
            "import json, logging, sys\n"
            "from vaultspec_a2a.utils import configure_logging, "
            "reconfigure_console_utf8\n"
            "reconfigure_console_utf8()\n"
            "configure_logging('protocol')\n"
            "logging.getLogger('bridge.test').warning('DIAG-ON-STDERR')\n"
            "sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 1, "
            "'result': 'ok'}) + '\\n')\n"
            "sys.stdout.flush()\n"
        ),
    )
    p = _run_child(child, env_extra={}, timeout=30.0)
    assert p.returncode == 0, p.stderr
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"jsonrpc": "2.0", "id": 1, "result": "ok"}
    assert not _has_log_json_on_stdout(p.stdout)
    assert "DIAG-ON-STDERR" in p.stderr


# --- entrypoint kind smoke tests -------------------------------------------


@pytest.mark.parametrize(
    ("which", "port_env", "expected_log"),
    [
        ("gateway", "VAULTSPEC_PORT", "gateway.log"),
        ("worker", "VAULTSPEC_WORKER_PORT", "worker.log"),
    ],
)
def test_service_entrypoint_creates_named_file_lane(
    tmp_path: Path, which: str, port_env: str, expected_log: str
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    imp = {
        "gateway": "from vaultspec_a2a.api.app import main",
        "worker": "from vaultspec_a2a.worker.app import main",
    }[which]
    child = _write_child(
        tmp_path,
        f"{which}_child.py",
        (
            f"{imp}\n"
            "try:\n"
            "    main()\n"
            "except BaseException:\n"
            "    pass\n"
        ),
    )
    # An invalid bind host makes uvicorn.run fail fast AFTER configure_logging has
    # already created the service file lane.
    env = {
        "VAULTSPEC_A2A_HOME": str(home),
        "VAULTSPEC_ENVIRONMENT": "production",
        "VAULTSPEC_HOST": "256.256.256.256",
        "VAULTSPEC_WORKER_HOST": "256.256.256.256",
        port_env: "8123",
    }
    _run_child(child, env_extra=env, timeout=40.0)
    assert (home / "runtime" / expected_log).exists()


def test_mcp_http_entrypoint_uses_service_lane(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    child = _write_child(
        tmp_path,
        "mcp_http_child.py",
        (
            "import sys\n"
            "sys.argv = ['prog', '--transport', 'streamable-http', "
            "'--host', '256.256.256.256']\n"
            "from vaultspec_a2a.protocols.mcp.__main__ import main\n"
            "try:\n"
            "    main()\n"
            "except BaseException:\n"
            "    pass\n"
        ),
    )
    _run_child(
        child,
        env_extra={
            "VAULTSPEC_A2A_HOME": str(home),
            "VAULTSPEC_ENVIRONMENT": "production",
        },
        timeout=40.0,
    )
    assert (home / "runtime" / "mcp.log").exists()


def test_mcp_stdio_entrypoint_keeps_stdout_clean(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    child = _write_child(
        tmp_path,
        "mcp_stdio_child.py",
        (
            "from vaultspec_a2a.protocols.mcp.__main__ import main\n"
            "main()\n"
        ),
    )
    # stdin is DEVNULL -> run_stdio_async hits EOF and exits; the protocol lane must
    # have kept stdout free of any log line.
    p = _run_child(
        child,
        env_extra={
            "VAULTSPEC_A2A_HOME": str(home),
            "VAULTSPEC_ENVIRONMENT": "production",
        },
        timeout=40.0,
    )
    assert not _has_log_json_on_stdout(p.stdout)


def test_cli_group_configures_cli_lane() -> None:
    from ...cli.main import main as cli

    # The group callback is the entrypoint's logging-wiring site; run it directly.
    cli.callback()  # type: ignore[misc]
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert any(getattr(h, "stream", None) is sys.stderr for h in root.handlers)
    assert not any(getattr(h, "stream", None) is sys.stdout for h in root.handlers)
