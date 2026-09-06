"""The pytest owner distinguishes a result from process-tree completion."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ..plugin import _write_completion_receipt
from ..runner import (
    COMPLETION_OWNER_PID_ENV,
    COMPLETION_RECEIPT_ENV,
    DESCENDANT_TIMEOUT_EXIT,
    TEARDOWN_TIMEOUT_EXIT,
)


def test_runner_reaps_a_process_that_hangs_after_its_passing_result() -> None:
    probe = Path(__file__).with_name("_runner_exit_probe.py")

    started = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.testing.runner",
            "--run-timeout",
            "30",
            "--exit-timeout",
            "1",
            "--",
            str(probe),
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == TEARDOWN_TIMEOUT_EXIT
    assert "[100%]" in completed.stdout
    assert "produced a session result" in completed.stderr
    assert "tree_reaped=true" in completed.stderr
    assert time.monotonic() - started < 15


def test_nested_pytest_process_cannot_complete_its_parent_receipt(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "parent-session-complete"
    old_receipt = os.environ.get(COMPLETION_RECEIPT_ENV)
    old_owner = os.environ.get(COMPLETION_OWNER_PID_ENV)
    try:
        os.environ[COMPLETION_RECEIPT_ENV] = str(receipt)
        os.environ[COMPLETION_OWNER_PID_ENV] = str(os.getpid() + 1)
        _write_completion_receipt(0)
    finally:
        if old_receipt is None:
            os.environ.pop(COMPLETION_RECEIPT_ENV, None)
        else:
            os.environ[COMPLETION_RECEIPT_ENV] = old_receipt
        if old_owner is None:
            os.environ.pop(COMPLETION_OWNER_PID_ENV, None)
        else:
            os.environ[COMPLETION_OWNER_PID_ENV] = old_owner
    assert not receipt.exists()


def test_runner_reaps_descendants_left_after_pytest_exits() -> None:
    probe = Path(__file__).with_name("_runner_descendant_probe.py")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.testing.runner",
            "--run-timeout",
            "30",
            "--exit-timeout",
            "1",
            "--",
            str(probe),
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == DESCENDANT_TIMEOUT_EXIT
    assert "1 passed" in completed.stdout
    assert "contained descendants" in completed.stderr
    assert "tree_reaped=true" in completed.stderr
