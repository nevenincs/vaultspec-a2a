"""Shared death-aware gateway boot for the real-process desktop gates.

Root cause of the recurring admission-gate flakes: every gate allocated a
port by bind-then-close, spawned the real gateway on it, and polled
``/health`` for up to 40 seconds. On Windows a freed port is not reserved -
late in a long suite another process can take it between the close and the
child's bind, the child dies on its bind, and the poll burns the whole
readiness window before failing with an opaque "never came up". Two
properties close the gap:

- **death-aware readiness**: the poll watches the child process; a gateway
  that exits before readiness fails IMMEDIATELY with its exit code and log
  tail (:class:`GatewayBootError`), never after a silent 40-second wait;
- **bind-race retry**: :func:`spawn_until_ready` re-allocates a fresh port
  and respawns on :class:`GatewayBootError`, bounded attempts. Only a DEAD
  child is retried - a live-but-unready gateway still fails loudly at the
  deadline, so a real boot regression cannot hide behind the retry. The
  attempts share one log file, so a retried run's log carries the dead
  attempt's bind error for diagnosis.

A boot that fails is also REAPED here rather than left running. The failure
mode this closes is cumulative, not local: a gateway that never became ready
is still a live process holding its port, its database handles, and its share
of the machine, and nothing downstream owns it - the caller's context manager
never received a handle to reap because the failure happened before the yield.
Every such failure therefore used to leak one gateway tree, and a handful of
them starve the box until later boots time out too, turning one real failure
into a cascade of unrelated ones.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "GatewayBootError",
    "await_gateway_ready",
    "free_port",
    "reap_gateway",
    "spawn_until_ready",
]

_LOG_TAIL_BYTES = 2048


class GatewayBootError(AssertionError):
    """The gateway process exited before its readiness endpoint answered."""


def free_port() -> int:
    """Return a currently-free loopback port (bind-then-close; racy by nature).

    The caller must treat the returned port as a CANDIDATE: nothing reserves
    it between this close and a child's bind, which is exactly why
    :func:`spawn_until_ready` retries a child that dies before readiness.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _log_tail(log_path: Path | None) -> str:
    if log_path is None:
        return ""
    try:
        data = log_path.read_bytes()
    except OSError:
        return ""
    tail = data[-_LOG_TAIL_BYTES:].decode("utf-8", errors="replace")
    return f"; log tail:\n{tail}" if tail else ""


def await_gateway_ready(
    base: str,
    proc: subprocess.Popen[bytes],
    *,
    log_path: Path | None = None,
    timeout: float = 40.0,
) -> None:
    """Wait until ``GET /health`` answers 200, failing FAST on a dead child.

    Raises :class:`GatewayBootError` the moment the spawned process exits
    before readiness (the bind-race signature), carrying the exit code and
    the log tail. A process that stays alive but never becomes ready raises
    a plain :class:`AssertionError` at the deadline - that is a genuine
    readiness failure and is never retried.
    """
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise GatewayBootError(
                f"gateway process exited before readiness "
                f"(exit {proc.returncode}){_log_tail(log_path)}"
            )
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:  # not up yet
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(
        f"gateway readiness never came up ({last}){_log_tail(log_path)}"
    )


def reap_gateway(proc: subprocess.Popen[bytes]) -> None:
    """Terminate a spawned gateway TREE, tolerating an already-dead child.

    The tree, not the handle: on Windows the virtual-environment interpreter is
    a launcher stub, so the real gateway - and any worker it auto-spawned - are
    descendants that outlive a kill aimed at the handle alone.
    """
    if proc.poll() is not None:
        return
    import asyncio

    from vaultspec_a2a.utils import kill_pid_tree_async

    with contextlib.suppress(Exception):
        asyncio.run(kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0))
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=15)


def spawn_until_ready(
    spawn: Callable[[int, int], subprocess.Popen[bytes]],
    *,
    log_path: Path | None = None,
    attempts: int = 3,
    timeout: float = 40.0,
) -> tuple[subprocess.Popen[bytes], int, int, str]:
    """Boot a gateway on a fresh port pair, retrying only the bind-race death.

    *spawn* receives ``(gateway_port, worker_port)`` and returns the spawned
    process; this drives up to *attempts* boots, each on freshly allocated
    ports, and returns ``(proc, gateway_port, worker_port, base)`` once the
    gateway answers its health endpoint. A child that dies before readiness
    is retried on new ports; the final attempt's failure propagates.

    Ownership of a FAILED boot ends here. Only a successful boot hands its
    process to the caller, so a child still running after a failed attempt has
    no other owner and is reaped before this returns or raises - including on
    an interrupt, which is when a leaked gateway is least likely to be noticed.
    """
    last_boot_error: GatewayBootError | None = None
    for _ in range(attempts):
        gateway_port = free_port()
        worker_port = free_port()
        proc = spawn(gateway_port, worker_port)
        base = f"http://127.0.0.1:{gateway_port}"
        try:
            await_gateway_ready(base, proc, log_path=log_path, timeout=timeout)
        except GatewayBootError as exc:
            # Called for symmetry and for the narrow window where the child died
            # between the poll and here; by this error's definition it is already
            # dead, so this is normally a no-op. It does NOT recover descendants
            # a dead child had already spawned - once the root pid is gone there
            # is no tree left to walk - which is why the harness relies on the
            # gateway's own containment for that case rather than on this call.
            reap_gateway(proc)
            last_boot_error = exc
            continue
        except BaseException:
            # Unready-at-deadline, interrupt, or anything else: this attempt
            # never becomes the caller's, so it must not outlive the failure.
            reap_gateway(proc)
            raise
        return proc, gateway_port, worker_port, base
    raise AssertionError(
        f"gateway did not boot within {attempts} attempts; last: {last_boot_error}"
    )
