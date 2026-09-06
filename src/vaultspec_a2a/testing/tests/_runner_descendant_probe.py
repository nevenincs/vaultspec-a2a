"""Subprocess-only probe that leaves a live descendant after pytest exits."""

import subprocess
import sys


def test_result_precedes_descendant_exit() -> None:
    subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
