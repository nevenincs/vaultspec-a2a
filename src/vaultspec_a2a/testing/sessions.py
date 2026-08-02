"""Machine-global test-session admission.

Concurrent test runs are a fact of this machine - parallel agents, parallel
suites, unrelated projects - so a run must be ADMITTED into that reality
rather than launched as if it owned the box. Two pieces deliver that:

- **Registration.** Every non-worker pytest session takes a SHARED lease on
  one well-known key at configure time, heartbeated and pid-reclaimed like
  every lease, which makes "how many test sessions are live right now" a
  cheap, honest machine-global question.
- **Capacity.** A distributed run derives its worker count from two limits
  composed by minimum: a fair share of the machine budget (the operator's
  explicit core budget or the core count, divided across live sessions) and
  the sampled free cores (covering load the session count cannot see). A
  second concurrent suite therefore proceeds DEGRADED instead of multiplying
  load quadratically; waiting was rejected because it turns every scoped run
  launched beside a long suite into an unbounded queue.

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


def _explicit_cpu_budget() -> int | None:
    """The operator's declared machine core budget for test work, or ``None``."""
    override = (os.environ.get(CPU_BUDGET_ENV) or "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return None


def machine_cpu_budget() -> int:
    """The whole-machine core budget test work may divide among sessions.

    The operator's explicit ``VAULTSPEC_TEST_CPU_BUDGET`` wins outright; else
    the plain core count. Deliberately NOT load-discounted: the peer division
    in :func:`effective_worker_count` accounts for peer sessions, and folding
    an instantaneous load sample (which already includes those peers' own
    consumption) into the divisible budget double-discounts them - on a busy
    box that floored the budget at one and switched the throughput layer off
    exactly when it was wanted.
    """
    explicit = _explicit_cpu_budget()
    if explicit is not None:
        return explicit
    return os.cpu_count() or 1


def _sampled_free_cores() -> int | None:
    """Cores the box has free right now by the load sample, or ``None``."""
    load = _sampled_load_percent()
    if load is None:
        return None
    cores = os.cpu_count() or 1
    return max(1, round(cores * (100 - load) / 100))


def effective_worker_count(
    requested: int, *, peers: int, cpu_budget: int | None = None
) -> int:
    """The worker count a distributed run is admitted with.

    Two independent limits compose by minimum, so neither is counted twice:
    the FAIR-SHARE limit divides the machine budget evenly across this session
    and its live peers (reserving room peers may ramp into), and the sampled
    FREE-CORES limit accounts for load the session count cannot see - other
    projects, non-test work. An explicit budget (the *cpu_budget* argument or
    the operator's env declaration) is authoritative and skips the sample.
    Never below one: a run always progresses.
    """
    explicit = cpu_budget if cpu_budget is not None else _explicit_cpu_budget()
    if explicit is not None:
        admitted = max(1, explicit // (peers + 1))
        return max(1, min(requested, admitted))
    cores = os.cpu_count() or 1
    admitted = max(1, cores // (peers + 1))
    free = _sampled_free_cores()
    if free is not None:
        admitted = max(1, min(admitted, free))
    return max(1, min(requested, admitted))
