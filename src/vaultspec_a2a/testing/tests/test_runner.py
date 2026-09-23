"""The pytest owner distinguishes a result from process-tree completion."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..children import (
    await_child,
    file_size_fingerprint,
    measured_child_startup_s,
    run_child,
)
from ..harness_names import COMPLETION_ENDPOINT_ENV, COMPLETION_OWNER_PID_ENV
from ..plugin import _send_completion_receipt
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


def _exit_timeout_s() -> float:
    """The teardown budget these probes run the owner under.

    DERIVED, not typed. The budget has to exceed what a real pytest teardown and
    interpreter exit cost on this host RIGHT NOW, and that cost scales with load
    exactly as a child's startup does - two orders of magnitude between an idle
    box and a concurrent suite. A literal comfortable on an idle host turns an
    honest slow exit into the very false exit-124 this module exists to prevent,
    so the budget is a multiple of the measured cost instead. Every proof below
    is stated relative to this value rather than to a number.

    The floor keeps an idle host's tiny measurement from producing a budget too
    small for a real teardown; the ceiling keeps one unlucky measurement from
    making every proof below wait minutes, since a pytest interpreter that has
    not exited half a minute after its session result is wedged on any host.
    """
    return min(30.0, max(5.0, 6.0 * measured_child_startup_s()))


def _result_to_exit_s(stderr: str) -> float:
    """The owner's OWN measurement of session result to teardown decision.

    The owner reports this interval on its teardown diagnostic. It is the clock
    the promptness proof needs: a caller's wall clock around the whole child
    also measures interpreter startup and collection, which are host-load
    artefacts and say nothing about whether ownership ended at the deadline.
    """
    marker = "result_to_exit="
    index = stderr.find(marker)
    assert index != -1, f"the owner reported no teardown interval: {stderr}"
    return float(stderr[index + len(marker) :].split("s", 1)[0])


def _readable(path: Path) -> str:
    """The text written so far, for a stall diagnostic; never itself a failure."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # the owner still holds the handle
        return f"<{path.name} unreadable: {exc}>"


def _run_runner(
    probe: Path,
    tmp_path: Path,
    *,
    runner_args: tuple[str, ...] = (),
    run_timeout_s: float | None = None,
) -> _RunnerResult:
    """Run the owner over *probe* and wait for it on progress, not a wall clock.

    The run timeout is opt-in: only the proof that the owner reaps a resultless
    run needs one, and imposing a wall clock on the others reproduced the
    failure mode under test - a loaded host's honest work exceeding a literal
    budget - as a test failure. The wait itself fails only when the owner tree
    stops burning CPU and stops writing, so an owner that is merely slow is
    never killed and a wedged one is reaped with its output attached.
    """
    stdout_path = tmp_path / "runner.stdout"
    stderr_path = tmp_path / "runner.stderr"
    timeout_args = (
        () if run_timeout_s is None else ("--run-timeout", f"{run_timeout_s:g}")
    )
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "vaultspec_a2a.testing.runner",
                *timeout_args,
                "--exit-timeout",
                f"{_exit_timeout_s():g}",
                *runner_args,
                "--",
                f"--confcutdir={probe.parent}",
                str(probe),
                "-q",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        returncode = await_child(
            process,
            what=f"the pytest owner over {probe.name}",
            fingerprint=file_size_fingerprint(stdout_path, stderr_path),
            diagnostic=lambda: _readable(stderr_path),
        )
    return _RunnerResult(
        returncode,
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
    child = run_child(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.testing.runner_child",
            f"--confcutdir={tmp_path}",
            str(probe),
            "-q",
        ],
        what="the runner child over the bootstrap probe",
        cwd=Path.cwd(),
        env=child_environment,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "1 passed" in child.stdout

    # `just init` provisions the checkout `.env` from `.env.example`, which
    # declares the development environment; the probe must not inherit that
    # declaration or it cannot observe the undeclared, fail-closed state.
    production = run_child(
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
        what="the undeclared-environment probe",
        cwd=Path.cwd(),
        env=child_environment,
    )
    assert production.returncode == 0, production.stdout + production.stderr
    assert production.stdout.strip() == "production-fail-closed"


def test_runner_reaps_a_process_that_hangs_after_its_passing_result(
    tmp_path: Path,
) -> None:
    """The owner reaps a hung teardown AT its deadline, neither early nor late.

    The probe passes and then never exits, so the owner's teardown deadline is
    the only thing that can end the run - it is given no run timeout at all
    here. Promptness is read from the owner's own result-to-exit measurement
    rather than from a wall clock around the child: the caller's clock also
    contains interpreter startup and collection, which vary with host load and
    would make this proof pass or fail on how busy the machine is.
    """
    probe = Path(__file__).with_name("_runner_exit_probe.py")
    exit_timeout = _exit_timeout_s()

    completed = _run_runner(probe, tmp_path)

    assert completed.returncode == TEARDOWN_TIMEOUT_EXIT
    assert "[100%]" in completed.stdout
    assert "produced a session result" in completed.stderr
    assert "tree_reaped=true" in completed.stderr
    assert "root_pid=" in completed.stderr
    assert "owned_pids=" in completed.stderr
    # Never early: the owner waited out the whole teardown budget before
    # reaping. Never late: it acted on that budget, not on some other wall.
    result_to_exit = _result_to_exit_s(completed.stderr)
    assert exit_timeout <= result_to_exit < 2 * exit_timeout + 10, completed.stderr


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
    pytest can spawn it. The outer test then remains active for twice the
    teardown budget, so a leaked nested completion channel would start the
    owner's teardown clock early and recreate the canonical false exit-124
    failure.

    The hold is expressed as a multiple of the budget rather than as a literal
    sleep, and the nested session is bounded by its own progress rather than by
    a wall clock: the three interpreters this starts cost a hundred milliseconds
    on an idle host and seconds on a loaded one, and a literal that spans both
    does not exist.
    """
    exit_timeout = _exit_timeout_s()
    outer = tmp_path / "test_nested_xdist_receipt.py"
    outer.write_text(
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "from vaultspec_a2a.testing.children import await_child\n"
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
        "    log = tmp_path / 'nested.log'\n"
        "    with log.open('wb') as handle:\n"
        "        nested_run = subprocess.Popen(\n"
        "            [sys.executable, '-m', 'pytest', str(nested), '-p',\n"
        "             'vaultspec_a2a.testing.plugin', '-p', 'no:cacheprovider',\n"
        "             '-n', '2', '--dist=loadgroup', '-q'],\n"
        "            cwd=nested, env=dict(os.environ),\n"
        "            stdout=handle, stderr=subprocess.STDOUT,\n"
        "        )\n"
        "        returncode = await_child(nested_run, what='the nested xdist run')\n"
        "    output = log.read_text(encoding='utf-8', errors='replace')\n"
        "    assert returncode == 0, output\n"
        f"    time.sleep({2 * exit_timeout:g})\n",
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

    completed = _run_runner(probe, tmp_path, run_timeout_s=0.1)

    assert completed.returncode == RUN_TIMEOUT_EXIT
    assert "did not produce a session result" in completed.stderr
    assert "tree_reaped=true" in completed.stderr
