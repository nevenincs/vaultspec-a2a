"""The pytest owner distinguishes a result from process-tree completion."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..harness_names import COMPLETION_ENDPOINT_ENV, COMPLETION_OWNER_PID_ENV
from ..plugin import send_completion_receipt
from ..runner import (
    DESCENDANT_TIMEOUT_EXIT,
    RUN_TIMEOUT_EXIT,
    TEARDOWN_TIMEOUT_EXIT,
    _completion_received,
)

if TYPE_CHECKING:
    import pytest


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
                f"--confcutdir={probe.parent}",
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
    child_environment.pop("VAULTSPEC_A2A_ENVIRONMENT", None)
    child_environment.pop("VAULTSPEC_A2A_INTERNAL_TOKEN", None)
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

    # `just init` provisions the checkout `.env` from `.env.example`, which
    # declares the development environment; the probe must not inherit that
    # declaration or it cannot observe the undeclared, fail-closed state.
    production = subprocess.run(
        [
            sys.executable,
            "-c",
            "from vaultspec_a2a.control.config import Settings; "
            "settings = Settings(_env_file=None); "
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
    assert "root_pid=" in completed.stderr
    assert "owned_pids=" in completed.stderr
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
        send_completion_receipt(0)
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


def test_completion_receiver_rejects_a_forged_sender_after_child_hello(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only the verified runner-child PID can finish an admitted session."""

    class _Containment:
        def is_designated_child(self, pid: int) -> bool:
            return pid == os.getpid()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.setblocking(False)
    host, port = listener.getsockname()
    try:
        with socket.create_connection((host, port)) as connection:
            connection.sendall(f"parent-token:{os.getpid()}:hello\n".encode())
        designated, completed = _completion_received(
            listener, "parent-token", _Containment(), None
        )
        assert designated == os.getpid()
        assert completed is False
        with socket.create_connection((host, port)) as connection:
            connection.sendall(f"parent-token:{os.getpid() + 1}:complete:0\n".encode())
        designated, completed = _completion_received(
            listener, "parent-token", _Containment(), designated
        )
        assert designated == os.getpid()
        assert completed is False
    finally:
        listener.close()
    assert "pytest completion receipt rejected: sender_pid=" in capsys.readouterr().err


def test_runner_rejects_a_rebound_nested_xdist_receipt(tmp_path: Path) -> None:
    """A nested xdist controller cannot start the outer teardown clock.

    The miniature child deliberately rebinds the former owner variable to its
    own PID, but the real runner child has already scrubbed the endpoint before
    pytest can spawn it. The outer test remains active longer than the
    one-second teardown budget, so a leaked nested completion channel would
    recreate the canonical false exit-124 failure.
    """
    outer = tmp_path / "test_nested_xdist_receipt.py"
    outer.write_text(
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "from vaultspec_a2a.testing.harness_names import COMPLETION_ENDPOINT_ENV\n"
        "\n"
        "def test_nested_xdist_cannot_finish_outer(tmp_path):\n"
        "    assert COMPLETION_ENDPOINT_ENV not in os.environ\n"
        "    nested = tmp_path / 'nested'\n"
        "    nested.mkdir()\n"
        "    (nested / 'conftest.py').write_text(\n"
        "        'import os\\n'\n"
        "        'from vaultspec_a2a.testing.harness_names import '\n"
        "        'COMPLETION_OWNER_PID_ENV\\n'\n"
        "        'os.environ[COMPLETION_OWNER_PID_ENV] = str(os.getpid())\\n'\n"
        "    )\n"
        "    (nested / 'test_inner.py').write_text(\n"
        "        'def test_one():\\n    assert True\\n'\n"
        "    )\n"
        "    completed = subprocess.run(\n"
        "        [sys.executable, '-m', 'pytest', str(nested), '-p',\n"
        "         'vaultspec_a2a.testing.plugin', '-p', 'no:cacheprovider',\n"
        "         '-n', '2', '--dist=loadgroup', '-q'],\n"
        "        cwd=nested, env=dict(os.environ), capture_output=True, text=True,\n"
        "        timeout=30, check=False,\n"
        "    )\n"
        "    assert completed.returncode == 0, completed.stdout + completed.stderr\n"
        "    time.sleep(1.2)\n",
        encoding="utf-8",
    )

    completed = _run_runner(outer, tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (
        "pytest completion hello accepted: designated_runner_child_pid="
        in completed.stderr
    )
    assert "pytest completion receipt accepted: sender_pid=" in completed.stderr


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
