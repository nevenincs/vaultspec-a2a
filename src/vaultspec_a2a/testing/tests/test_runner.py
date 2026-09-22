"""The pytest owner distinguishes a result from process-tree completion."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

from ..plugin import _send_completion_receipt
from ..runner import (
    COMPLETION_ENDPOINT_ENV,
    COMPLETION_OWNER_PID_ENV,
    DESCENDANT_TIMEOUT_EXIT,
    RUN_TIMEOUT_EXIT,
    TEARDOWN_TIMEOUT_EXIT,
)


class _RunnerResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _run_runner(
    probe: Path,
    tmp_path: Path,
    *,
    runner_args: tuple[str, ...] = (),
) -> _RunnerResult:
    stdout_path = tmp_path / "runner.stdout"
    stderr_path = tmp_path / "runner.stderr"
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "vaultspec_a2a.testing.runner",
                "--run-timeout",
                "30",
                "--exit-timeout",
                "1",
                *runner_args,
                "--",
                str(probe),
                "-q",
            ],
            stdout=stdout,
            stderr=stderr,
            timeout=30,
            check=False,
        )
    return _RunnerResult(
        completed.returncode,
        stdout_path.read_text(encoding="utf-8"),
        stderr_path.read_text(encoding="utf-8"),
    )


def test_runner_child_declares_test_environment_before_settings_import(
    tmp_path: Path,
) -> None:
    """The child opts into test auth before importing the settings singleton."""
    probe = tmp_path / "test_bootstrap_probe.py"
    probe.write_text(
        "from vaultspec_a2a.control.config import settings\n"
        "from vaultspec_a2a.utils.ipc_auth import ("
        "BearerVerdict, verify_internal_bearer)\n"
        "\n"
        "def test_child_bootstrap():\n"
        "    assert settings.environment.value == 'development'\n"
        "    assert settings.environment_declared is True\n"
        "    verdict, _ = verify_internal_bearer(\n"
        "        None,\n"
        "        token=settings.internal_token,\n"
        "        environment=settings.environment,\n"
        "        environment_declared=settings.environment_declared,\n"
        "    )\n"
        "    assert verdict is BearerVerdict.OK\n",
        encoding="utf-8",
    )

    child_environment = os.environ.copy()
    child_environment.pop("VAULTSPEC_ENVIRONMENT", None)
    child_environment.pop("VAULTSPEC_INTERNAL_TOKEN", None)
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.testing.runner_child",
            f"--confcutdir={tmp_path}",
            str(probe),
            "-q",
        ],
        cwd=Path.cwd(),
        env=child_environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "1 passed" in child.stdout

    production = subprocess.run(
        [
            sys.executable,
            "-c",
            "from vaultspec_a2a.control.config import settings; "
            "from vaultspec_a2a.utils.ipc_auth import verify_internal_bearer; "
            "verdict, _ = verify_internal_bearer("
            "None, token=settings.internal_token, environment=settings.environment, "
            "environment_declared=settings.environment_declared); "
            "assert settings.environment_declared is False; "
            "assert verdict.value == 'misconfigured'; print('production-fail-closed')",
        ],
        cwd=Path.cwd(),
        env=child_environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert production.returncode == 0, production.stdout + production.stderr
    assert production.stdout.strip() == "production-fail-closed"


def test_runner_reaps_a_process_that_hangs_after_its_passing_result(
    tmp_path: Path,
) -> None:
    probe = Path(__file__).with_name("_runner_exit_probe.py")

    started = time.monotonic()
    completed = _run_runner(probe, tmp_path)

    assert completed.returncode == TEARDOWN_TIMEOUT_EXIT
    assert "[100%]" in completed.stdout
    assert "produced a session result" in completed.stderr
    assert "tree_reaped=true" in completed.stderr
    assert time.monotonic() - started < 15


def test_nested_pytest_process_cannot_complete_its_parent_receipt() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    old_endpoint = os.environ.get(COMPLETION_ENDPOINT_ENV)
    old_owner = os.environ.get(COMPLETION_OWNER_PID_ENV)
    try:
        os.environ[COMPLETION_ENDPOINT_ENV] = f"127.0.0.1:{port}:parent-token"
        os.environ[COMPLETION_OWNER_PID_ENV] = str(os.getpid() + 1)
        _send_completion_receipt(0)
        try:
            listener.accept()
        except BlockingIOError:
            pass
        else:
            raise AssertionError("nested pytest sent its parent's completion receipt")
    finally:
        listener.close()
        if old_endpoint is None:
            os.environ.pop(COMPLETION_ENDPOINT_ENV, None)
        else:
            os.environ[COMPLETION_ENDPOINT_ENV] = old_endpoint
        if old_owner is None:
            os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
        else:
            os.environ[COMPLETION_OWNER_PID_ENV] = old_owner


def test_runner_reaps_descendants_left_after_pytest_exits(tmp_path: Path) -> None:
    probe = Path(__file__).with_name("_runner_descendant_probe.py")

    completed = _run_runner(probe, tmp_path)

    assert completed.returncode == DESCENDANT_TIMEOUT_EXIT
    assert "1 passed" in completed.stdout
    assert "contained descendants" in completed.stderr
    assert "tree_reaped=true" in completed.stderr


def test_runner_reports_progress_before_a_session_result(tmp_path: Path) -> None:
    probe = Path(__file__).with_name("_runner_progress_probe.py")

    completed = _run_runner(
        probe,
        tmp_path,
        runner_args=("--progress-interval", "0.1"),
    )

    assert completed.returncode == 0
    assert "pytest owner started:" in completed.stderr
    assert "phase=awaiting_session_result" in completed.stderr
    assert "pytest owner progress:" in completed.stderr


def test_runner_reaps_a_run_without_a_session_result(tmp_path: Path) -> None:
    probe = Path(__file__).with_name("_runner_progress_probe.py")

    completed = _run_runner(probe, tmp_path, runner_args=("--run-timeout", "0.1"))

    assert completed.returncode == RUN_TIMEOUT_EXIT
    assert "did not produce a session result" in completed.stderr
    assert "tree_reaped=true" in completed.stderr
