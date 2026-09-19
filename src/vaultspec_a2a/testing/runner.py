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
import hmac
import os
import secrets
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING, cast

from ..utils.process import ProcessContainment, ProcessContainmentError

if TYPE_CHECKING:
    from collections.abc import Sequence

COMPLETION_ENDPOINT_ENV = "VAULTSPEC_PYTEST_COMPLETION_ENDPOINT"
COMPLETION_OWNER_PID_ENV = "VAULTSPEC_PYTEST_COMPLETION_OWNER_PID"
TEARDOWN_TIMEOUT_EXIT = 124
RUN_TIMEOUT_EXIT = 125
DESCENDANT_TIMEOUT_EXIT = 126
_POLL_SECONDS = 0.05
_DEFAULT_PROGRESS_INTERVAL_SECONDS = 30.0


def _completion_received(listener: socket.socket, token: str) -> bool:
    """Accept one bounded authenticated completion message without blocking."""
    try:
        connection, _address = listener.accept()
    except BlockingIOError:
        return False
    with connection:
        connection.settimeout(0.1)
        received = bytearray()
        try:
            while len(received) < 256 and b"\n" not in received:
                chunk = connection.recv(256 - len(received))
                if not chunk:
                    break
                received.extend(chunk)
            payload = bytes(received).decode("ascii")
        except (OSError, UnicodeDecodeError):
            return False
    supplied, separator, exitstatus = payload.partition(":")
    return bool(
        separator
        and exitstatus.rstrip("\n").lstrip("-").isdigit()
        and hmac.compare_digest(supplied, token)
    )


def _terminate(
    containment: ProcessContainment, process: subprocess.Popen[bytes]
) -> bool:
    tree_reaped = asyncio.run(containment.terminate(term_timeout=2.0, kill_timeout=5.0))
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
    progress_interval_s: float = _DEFAULT_PROGRESS_INTERVAL_SECONDS,
) -> int:
    """Run pytest under OS containment and enforce result-to-exit ownership."""
    if exit_timeout_s <= 0:
        raise ValueError("exit_timeout_s must be positive")
    if run_timeout_s is not None and run_timeout_s <= 0:
        raise ValueError("run_timeout_s must be positive when supplied")
    if progress_interval_s <= 0:
        raise ValueError("progress_interval_s must be positive")

    containment = ProcessContainment.create()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        token = secrets.token_hex(32)
        endpoint = f"127.0.0.1:{port}:{token}"
        env = {**os.environ, COMPLETION_ENDPOINT_ENV: endpoint}
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
        next_progress = started + progress_interval_s
        completion_seen: float | None = None
        root_exit_seen: float | None = None
        run_timeout = "unbounded" if run_timeout_s is None else f"{run_timeout_s:g}s"
        print(
            "pytest owner started: "
            f"pid={process.pid} phase=awaiting_session_result "
            f"run_timeout={run_timeout} exit_timeout={exit_timeout_s:g}s",
            file=sys.stderr,
            flush=True,
        )
        try:
            while True:
                returncode = process.poll()
                now = time.monotonic()
                if completion_seen is None and _completion_received(listener, token):
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
                if completion_seen is None and now >= next_progress:
                    print(
                        "pytest owner progress: "
                        f"pid={process.pid} phase=awaiting_session_result "
                        f"elapsed={now - started:.1f}s",
                        file=sys.stderr,
                        flush=True,
                    )
                    next_progress = now + progress_interval_s
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
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=_DEFAULT_PROGRESS_INTERVAL_SECONDS,
    )
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
            progress_interval_s=args.progress_interval,
        )
    except (OSError, ProcessContainmentError, subprocess.SubprocessError) as exc:
        print(f"pytest process ownership failed: {exc}", file=sys.stderr, flush=True)
        return RUN_TIMEOUT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
