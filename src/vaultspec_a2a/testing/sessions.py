"""Machine-global test-session admission.

Concurrent test runs are a fact of this machine - parallel agents, parallel
suites, unrelated projects - so a run must be ADMITTED into that reality
rather than launched as if it owned the box. Two pieces deliver that:

- **Registration.** Every non-worker pytest session takes a SHARED lease on
  one well-known key at configure time, heartbeated and pid-reclaimed like
  every lease, which makes "how many test sessions are live right now" a
  cheap, honest machine-global question.
- **Capacity.** A distributed run derives its worker count from what the box
  actually has free: the operator's explicit core budget when declared, else
  the core count discounted by a sampled machine-load estimate, divided
  across the live peer sessions. A second concurrent suite therefore proceeds
  DEGRADED instead of multiplying load quadratically; waiting was rejected
  because it turns every scoped run launched beside a long suite into an
  unbounded queue.

Correctness never rests on any of this - the lease and reservation layers
serialize the genuinely contended resources regardless - so admission is
purely a throughput policy and fails open: a run that cannot register still
runs, serially safe, with a visible warning.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from .leases import (
    Lease,
    LeaseAcquisitionTimeoutError,
    acquire,
    live_shared_holder_count,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CPU_BUDGET_ENV",
    "SESSION_LEASE_KEY",
    "effective_worker_count",
    "live_peer_sessions",
    "machine_cpu_budget",
    "register_session",
]

logger = logging.getLogger(__name__)

SESSION_LEASE_KEY = "pytest-session"
# Operator override: the number of cores this run may assume are its own.
# Explicit and environment-driven, per the strict production policy; when set
# it replaces the sampled load estimate entirely.
CPU_BUDGET_ENV = "VAULTSPEC_TEST_CPU_BUDGET"

# Registration must never wedge a run: admission is throughput bookkeeping,
# not a correctness gate, so a contended session key (which would take a
# deliberately-held exclusive lease on the session key - nothing in the
# repository takes one) degrades to running unregistered after this wait.
_REGISTER_TIMEOUT_S = 10.0


def register_session(*, home: Path | None = None) -> Lease | None:
    """Register this pytest session machine-globally; ``None`` on failure.

    A shared lease, so any number of sessions coexist and each is counted
    while its pid lives and its heartbeat refreshes. Failure is logged and
    tolerated - an unregistered session under-counts peers, which degrades
    throughput for others, never correctness.
    """
    try:
        return acquire(
            SESSION_LEASE_KEY,
            shared=True,
            owner=f"pytest-{os.getpid()}",
            home=home,
            acquire_timeout_s=_REGISTER_TIMEOUT_S,
        )
    except (LeaseAcquisitionTimeoutError, OSError, ValueError) as exc:
        logger.warning(
            "test session registration failed; running unregistered: %s", exc
        )
        return None


def live_peer_sessions(*, home: Path | None = None) -> int:
    """Live registered test sessions on this machine, excluding this process."""
    return live_shared_holder_count(
        SESSION_LEASE_KEY, home=home, excluding_pid=os.getpid()
    )


def _sampled_load_percent() -> int | None:
    """A one-shot machine CPU-load estimate in percent, or ``None``.

    POSIX reads the one-minute load average against the core count; Windows
    asks WMI for the processors' load percentage through PowerShell. Both are
    coarse single samples by design - admission needs an honest order of
    magnitude, not telemetry - and any failure reads as ``None`` so capacity
    degrades to the plain core count.
    """
    cores = os.cpu_count() or 1
    if hasattr(os, "getloadavg"):
        try:
            one_minute = os.getloadavg()[0]
        except OSError:
            return None
        return max(0, min(100, round(one_minute / cores * 100)))
    if sys.platform == "win32":
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Measure-Object "
                    "-Property LoadPercentage -Average).Average",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        raw = completed.stdout.strip()
        try:
            return max(0, min(100, round(float(raw))))
        except ValueError:
            return None
    return None


def machine_cpu_budget() -> int:
    """The cores this run may assume are available to test work.

    The operator's explicit ``VAULTSPEC_TEST_CPU_BUDGET`` wins outright; else
    the core count discounted by the sampled load estimate; else the plain
    core count. Never below one.
    """
    override = (os.environ.get(CPU_BUDGET_ENV) or "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    cores = os.cpu_count() or 1
    load = _sampled_load_percent()
    if load is None:
        return cores
    return max(1, round(cores * (100 - load) / 100))


def effective_worker_count(
    requested: int, *, peers: int, cpu_budget: int | None = None
) -> int:
    """The worker count a distributed run is admitted with.

    The budget is split evenly across this session and its live peers, and the
    request is capped to this session's share - concurrency stays a
    consequence of what the machine actually has free, never an assumption of
    ownership. Never below one: a run always progresses.
    """
    budget = cpu_budget if cpu_budget is not None else machine_cpu_budget()
    share = max(1, budget // (peers + 1))
    return max(1, min(requested, share))
