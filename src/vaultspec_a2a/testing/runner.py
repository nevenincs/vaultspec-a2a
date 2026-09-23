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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..utils.process import ProcessContainment, ProcessContainmentError
from .harness_names import COMPLETION_ENDPOINT_ENV, COMPLETION_OWNER_PID_ENV

if TYPE_CHECKING:
    from collections.abc import Sequence


TEARDOWN_TIMEOUT_EXIT = 124
RUN_TIMEOUT_EXIT = 125
DESCENDANT_TIMEOUT_EXIT = 126
_POLL_SECONDS = 0.05
_DEFAULT_PROGRESS_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class _RunLimits:
    exit_timeout_s: float
    run_timeout_s: float | None
    progress_interval_s: float


class _CompletionContainment(Protocol):
    def is_designated_child(self, pid: int) -> bool: ...


@dataclass(frozen=True)
class _CompletionChannel:
    """The fixed identity of one run's completion socket, bundled for passing."""

    listener: socket.socket
    token: str
    containment: _CompletionContainment


@dataclass
class _ProgressReporter:
    started: float
    next_progress: float
    interval_s: float

    def report_if_due(
        self,
        process: subprocess.Popen[bytes],
        completion_seen: float | None,
        now: float,
    ) -> None:
        if completion_seen is not None or now < self.next_progress:
            return
        print(
            "pytest owner progress: "
            f"pid={process.pid} phase=awaiting_session_result "
            f"elapsed={now - self.started:.1f}s",
            file=sys.stderr,
            flush=True,
        )
        self.next_progress = now + self.interval_s


def _receive_completion_payload(listener: socket.socket) -> str | None:
    """Read one bounded, newline-terminated payload, or ``None`` on any failure."""
    try:
        connection, _address = listener.accept()
    except BlockingIOError:
        return None
    with connection:
        connection.settimeout(0.1)
        received = bytearray()
        try:
            while len(received) < 256 and b"\n" not in received:
                chunk = connection.recv(256 - len(received))
                if not chunk:
                    break
                received.extend(chunk)
            return bytes(received).decode("ascii")
        except (OSError, UnicodeDecodeError):
            return None


def _parsed_completion_fields(payload: str, token: str) -> tuple[int, str, str] | None:
    """Return ``(sender_pid, message_type, exitstatus)`` once the token checks out."""
    fields = payload.rstrip("\n").split(":")
    if len(fields) not in {3, 4}:
        return None
    supplied, sender_text, message_type, *status_fields = fields
    exitstatus = status_fields[0] if len(status_fields) == 1 else ""
    if not (
        sender_text.isdigit()
        and message_type in {"hello", "complete"}
        and hmac.compare_digest(supplied, token)
    ):
        return None
    return int(sender_text), message_type, exitstatus


def _handle_completion_hello(
    sender_pid: int,
    exitstatus: str,
    containment: _CompletionContainment,
    designated_pid: int | None,
) -> tuple[int | None, bool]:
    invalid_hello = (
        exitstatus
        or designated_pid is not None
        or not containment.is_designated_child(sender_pid)
    )
    if invalid_hello:
        print(
            "pytest completion hello rejected: "
            f"sender_pid={sender_pid} designated_pid={designated_pid}",
            file=sys.stderr,
            flush=True,
        )
        return designated_pid, False
    print(
        f"pytest completion hello accepted: designated_runner_child_pid={sender_pid}",
        file=sys.stderr,
        flush=True,
    )
    return sender_pid, False


def _handle_completion_complete(
    sender_pid: int, exitstatus: str, designated_pid: int | None
) -> tuple[int | None, bool]:
    valid_status = exitstatus.rstrip("\n").lstrip("-").isdigit()
    if not valid_status or sender_pid != designated_pid:
        print(
            "pytest completion receipt rejected: "
            f"sender_pid={sender_pid} designated_runner_child_pid={designated_pid}",
            file=sys.stderr,
            flush=True,
        )
        return designated_pid, False
    print(
        "pytest completion receipt accepted: "
        f"sender_pid={sender_pid} exitstatus={exitstatus.rstrip()}",
        file=sys.stderr,
        flush=True,
    )
    return designated_pid, True


def _completion_received(
    listener: socket.socket,
    token: str,
    containment: _CompletionContainment,
    designated_pid: int | None,
) -> tuple[int | None, bool]:
    """Accept completion only from the designated runner child.

    The endpoint token authenticates the owner channel, but environment values
    are inherited by ordinary nested subprocesses.  The receipt therefore also
    carries the sender's actual process id. The initial ``hello`` pins the
    runner child's verified launcher descendant before pytest can spawn nested
    processes; a later ``complete`` must come from that exact identity.
    """
    payload = _receive_completion_payload(listener)
    if payload is None:
        return designated_pid, False
    parsed = _parsed_completion_fields(payload, token)
    if parsed is None:
        return designated_pid, False
    sender_pid, message_type, exitstatus = parsed
    if message_type == "hello":
        return _handle_completion_hello(
            sender_pid, exitstatus, containment, designated_pid
        )
    return _handle_completion_complete(sender_pid, exitstatus, designated_pid)


def _terminate(
    containment: ProcessContainment, process: subprocess.Popen[bytes]
) -> bool:
    tree_reaped = asyncio.run(containment.terminate(term_timeout=2.0, kill_timeout=5.0))
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        return False
    return tree_reaped


def _timeout_context(
    process: subprocess.Popen[bytes], containment: ProcessContainment
) -> str:
    """Return safe, pre-reap ownership evidence for a timeout diagnostic."""
    return (
        f"root_pid={process.pid} root_returncode={process.poll()} "
        f"{containment.diagnostic_snapshot()}"
    )


def _spawn_pytest_process(
    pytest_args: Sequence[str], containment: ProcessContainment, endpoint: str
) -> subprocess.Popen[bytes]:
    env: dict[str, str] = dict(os.environ)
    env[COMPLETION_ENDPOINT_ENV] = endpoint
    # A caller cannot accidentally donate a stale owner identity to the child.
    # ``runner_child`` also clears it around pytest; retaining both boundaries
    # makes the spawn contract explicit before any child instructions execute.
    env.pop(COMPLETION_OWNER_PID_ENV, None)
    python_executable = sys.executable
    if not python_executable:
        raise OSError("Python executable is unavailable for pytest ownership")
    # Launched with -m, never -c: an xdist worker is recognised by execnet's
    # `python -c` bootstrap, and a nested session launched that way would take
    # its parent's seat and clear the parent's live basetemp.
    command = [
        python_executable,
        "-m",
        "vaultspec_a2a.testing.runner_child",
        *pytest_args,
    ]
    spawn_kwargs = containment.spawn_kwargs()
    start_new_session = bool(spawn_kwargs.get("start_new_session", False))
    try:
        return subprocess.Popen(
            command,
            stdin=None,
            stdout=None,
            stderr=None,
            env=env,
            creationflags=containment.suspended_creation_flag(),
            start_new_session=start_new_session,
            text=False,
            encoding=None,
            errors=None,
        )
    except BaseException:
        containment.close()
        raise


def _assign_pytest_process(
    process: subprocess.Popen[bytes], containment: ProcessContainment
) -> None:
    try:
        containment.assign_suspended_process(process)
    except BaseException:
        # Assignment may leave either an owned tree or an unassigned root.
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


def _root_exit_status(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    first_seen: float | None,
    now: float,
    timeout_s: float,
) -> tuple[int | None, float]:
    if containment.is_quiescent() is True:
        containment.close()
        return process.returncode, now
    first_seen = now if first_seen is None else first_seen
    if now - first_seen >= timeout_s:
        context = _timeout_context(process, containment)
        reaped = _terminate(containment, process)
        print(
            "pytest exited but its contained descendants did not "
            f"exit within {timeout_s:g}s; tree_reaped={str(reaped).lower()} "
            f"{context}",
            file=sys.stderr,
            flush=True,
        )
        return DESCENDANT_TIMEOUT_EXIT, first_seen
    return None, first_seen


def _teardown_timeout_status(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    completion_seen: float | None,
    now: float,
    timeout_s: float,
) -> int | None:
    if completion_seen is None or now - completion_seen < timeout_s:
        return None
    # The interval from the session result to this decision, measured by the
    # owner itself. It is the only clock that says whether the teardown deadline
    # or some unrelated wall ended the run, and unlike a caller's wall clock it
    # excludes interpreter startup and collection - costs that vary by two
    # orders of magnitude with host load and say nothing about ownership.
    result_to_exit = now - completion_seen
    context = _timeout_context(process, containment)
    reaped = _terminate(containment, process)
    print(
        "pytest produced a session result but its owned process tree "
        f"did not exit within {timeout_s:g}s; tree_reaped={str(reaped).lower()} "
        f"result_to_exit={result_to_exit:.3f}s {context}",
        file=sys.stderr,
        flush=True,
    )
    return TEARDOWN_TIMEOUT_EXIT


def _run_timeout_status(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    started: float,
    now: float,
    timeout_s: float | None,
) -> int | None:
    if timeout_s is None or now - started < timeout_s:
        return None
    context = _timeout_context(process, containment)
    reaped = _terminate(containment, process)
    print(
        "pytest did not produce a session result within "
        f"{timeout_s:g}s; tree_reaped={str(reaped).lower()} {context}",
        file=sys.stderr,
        flush=True,
    )
    return RUN_TIMEOUT_EXIT


def _completion_time(
    channel: _CompletionChannel,
    designated_pid: int | None,
    completion_seen: float | None,
    now: float,
) -> tuple[int | None, float | None]:
    if completion_seen is not None:
        return designated_pid, completion_seen
    designated_pid, received = _completion_received(
        channel.listener, channel.token, channel.containment, designated_pid
    )
    return designated_pid, now if received else completion_seen


def _await_pytest_exit(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    listener: socket.socket,
    token: str,
    limits: _RunLimits,
) -> int:
    started = time.monotonic()
    progress = _ProgressReporter(
        started, started + limits.progress_interval_s, limits.progress_interval_s
    )
    channel = _CompletionChannel(listener, token, containment)
    completion_seen: float | None = None
    designated_pid: int | None = None
    root_exit_seen: float | None = None
    run_timeout = (
        "unbounded" if limits.run_timeout_s is None else f"{limits.run_timeout_s:g}s"
    )
    print(
        "pytest owner started: "
        f"pid={process.pid} phase=awaiting_session_result "
        f"run_timeout={run_timeout} exit_timeout={limits.exit_timeout_s:g}s",
        file=sys.stderr,
        flush=True,
    )
    try:
        while True:
            returncode = process.poll()
            now = time.monotonic()
            designated_pid, completion_seen = _completion_time(
                channel, designated_pid, completion_seen, now
            )
            # A root may terminate between the first poll and receipt
            # observation. Re-sample before applying the post-receipt timeout;
            # otherwise a scheduling boundary can misclassify a root exit as a
            # teardown timeout and never reach descendant classification.
            if returncode is None and completion_seen is not None:
                returncode = process.poll()
            if returncode is not None:
                status, root_exit_seen = _root_exit_status(
                    process, containment, root_exit_seen, now, limits.exit_timeout_s
                )
            else:
                status = _teardown_timeout_status(
                    process, containment, completion_seen, now, limits.exit_timeout_s
                )
            if status is not None:
                return status
            status = _run_timeout_status(
                process, containment, started, now, limits.run_timeout_s
            )
            if status is not None:
                return status
            progress.report_if_due(process, completion_seen, now)
            time.sleep(_POLL_SECONDS)
    finally:
        if process.poll() is None:
            _terminate(containment, process)
        else:
            containment.close()


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
        process = _spawn_pytest_process(pytest_args, containment, endpoint)
        _assign_pytest_process(process, containment)

        return _await_pytest_exit(
            process,
            containment,
            listener,
            token,
            _RunLimits(exit_timeout_s, run_timeout_s, progress_interval_s),
        )


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
