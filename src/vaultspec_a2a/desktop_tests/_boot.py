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
"""

from __future__ import annotations

import socket
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "GatewayBootError",
    "await_gateway_ready",
    "free_port",
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
            last_boot_error = exc
            continue
        return proc, gateway_port, worker_port, base
    raise AssertionError(
        f"gateway did not boot within {attempts} attempts; last: {last_boot_error}"
    )
