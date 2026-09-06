"""Bounded process owner for pytest sessions.

Pytest owns test execution and fixture teardown.  This wrapper owns the process
that performs them.  The plugin writes a completion receipt when pytest has
finished its session result; if the interpreter then fails to exit, the wrapper
reaps the complete contained process tree after a short teardown deadline.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..utils.process import ProcessContainment, ProcessContainmentError

if TYPE_CHECKING:
    from collections.abc import Sequence

COMPLETION_RECEIPT_ENV = "VAULTSPEC_PYTEST_COMPLETION_RECEIPT"
COMPLETION_OWNER_PID_ENV = "VAULTSPEC_PYTEST_COMPLETION_OWNER_PID"
TEARDOWN_TIMEOUT_EXIT = 124
RUN_TIMEOUT_EXIT = 125
DESCENDANT_TIMEOUT_EXIT = 126
_POLL_SECONDS = 0.05


def _terminate(
    containment: ProcessContainment, process: subprocess.Popen[bytes]
) -> bool:
    tree_reaped = asyncio.run(
        containment.terminate(term_timeout=2.0, kill_timeout=5.0)
    )
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        return False
    return tree_reaped


def run_pytest(
    pytest_args: Sequence[str],
    *,
    exit_timeout_s: float,
    run_timeout_s: float | None = None,
) -> int:
    """Run pytest under OS containment and enforce result-to-exit ownership."""
    if exit_timeout_s <= 0:
        raise ValueError("exit_timeout_s must be positive")
    if run_timeout_s is not None and run_timeout_s <= 0:
        raise ValueError("run_timeout_s must be positive when supplied")

    containment = ProcessContainment.create()
    with tempfile.TemporaryDirectory(prefix="vaultspec-pytest-owner-") as scratch:
        receipt = Path(scratch) / "session-complete"
        env = {**os.environ, COMPLETION_RECEIPT_ENV: str(receipt)}
        command = [
            sys.executable,
            "-m",
            "vaultspec_a2a.testing.runner_child",
            *pytest_args,
        ]
        creationflags = containment.suspended_creation_flag()
        try:
            process = cast(
                "subprocess.Popen[bytes]",
                subprocess.Popen(
                    command,
                    env=env,
                    creationflags=creationflags,
                    **containment.spawn_kwargs(),
                ),
            )
        except BaseException:
            containment.close()
            raise
        try:
            containment.assign_suspended_process(process)
        except BaseException:
            # Assignment/resume can fail with either an unassigned retained
            # root or an already-assigned job. Reap through both authorities;
            # neither cleanup failure may hide the original ownership error.
            try:
                if containment.assigned:
                    _terminate(containment, process)
                elif process.poll() is None:
                    process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5.0)
            finally:
                containment.close()
            raise

        started = time.monotonic()
        completion_seen: float | None = None
        root_exit_seen: float | None = None
        try:
            while True:
                returncode = process.poll()
                now = time.monotonic()
                if completion_seen is None and receipt.is_file():
                    completion_seen = now
                if returncode is not None:
                    if containment.is_quiescent() is True:
                        containment.close()
                        return returncode
                    if root_exit_seen is None:
                        root_exit_seen = now
                    if now - root_exit_seen >= exit_timeout_s:
                        reaped = _terminate(containment, process)
                        print(
                            "pytest exited but its contained descendants did not "
                            f"exit within {exit_timeout_s:g}s; "
                            f"tree_reaped={str(reaped).lower()}",
                            file=sys.stderr,
                            flush=True,
                        )
                        return DESCENDANT_TIMEOUT_EXIT
                if (
                    returncode is None
                    and completion_seen is not None
                    and now - completion_seen >= exit_timeout_s
                ):
                    reaped = _terminate(containment, process)
                    print(
                        "pytest produced a session result but its owned process tree "
                        f"did not exit within {exit_timeout_s:g}s; "
                        f"tree_reaped={str(reaped).lower()}",
                        file=sys.stderr,
                        flush=True,
                    )
                    return TEARDOWN_TIMEOUT_EXIT
                if run_timeout_s is not None and now - started >= run_timeout_s:
                    reaped = _terminate(containment, process)
                    print(
                        "pytest did not produce a session result within "
                        f"{run_timeout_s:g}s; tree_reaped={str(reaped).lower()}",
                        file=sys.stderr,
                        flush=True,
                    )
                    return RUN_TIMEOUT_EXIT
                time.sleep(_POLL_SECONDS)
        finally:
            if process.poll() is None:
                _terminate(containment, process)
            else:
                containment.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run pytest with bounded ownership after its session result."
    )
    parser.add_argument("--exit-timeout", type=float, default=10.0)
    parser.add_argument("--run-timeout", type=float)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args.pop(0)
    try:
        return run_pytest(
            pytest_args,
            exit_timeout_s=args.exit_timeout,
            run_timeout_s=args.run_timeout,
        )
    except (OSError, ProcessContainmentError, subprocess.SubprocessError) as exc:
        print(f"pytest process ownership failed: {exc}", file=sys.stderr, flush=True)
        return RUN_TIMEOUT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
