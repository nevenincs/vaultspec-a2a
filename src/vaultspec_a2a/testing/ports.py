"""The one canonical way a test acquires a port.

Tests never name a port; they take what they are given. Acquisition rides the
dev-process registry's existing race-free allocate-and-claim - an ``O_EXCL``
reservation marker in the machine-global procs home over the committed scratch
band - so two concurrent claimants (workers, sessions, agents) can never be
handed the same port.

Three entry points live here because there are three genuinely different
questions a caller can be asking, and collapsing them would be worse than the
duplication that used to separate them:

- :func:`reserved_port` holds a claim for the duration of a ``with`` block and
  releases it on exit. Take this when the test owns a bounded window.
- :func:`free_port` holds a claim for the whole PROCESS lifetime and returns a
  bare port number. Take this when there is no teardown moment to release in -
  a module-level constant, a child process's port, a negative test asserting
  nothing answers. A reservation is not a bind, so the returned port still has
  no listener on it, which is what those negative callers assert against.
- :func:`allocate_free_ports` asks the OS for currently-unoccupied ports and
  hands out NO claim at all. It is the FALLBACK for a missing band config or an
  exhausted band, not a peer of the other two, and it must never be used to
  obtain a port a test will bind while anything else could take it.

The band-backed paths are the default-safe ones: allocation arbitrates through
the machine-global registry FIRST, and the unclaimed OS candidate is what a
caller degrades to rather than failing a run over allocation policy.

This module is the home for ACQUIRING a port. It is not the production port
machinery - :mod:`vaultspec_a2a.lifecycle.registry` owns reservation, liveness
and band policy for real services, and this builds on it - and it is not
service DISCOVERY, which is :mod:`vaultspec_a2a.testing.endpoints`.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import socket
import threading
from typing import TYPE_CHECKING

from ..lifecycle import (
    ProcsConfig,
    load_procs_config,
    release_reservation,
    reserve_port,
)
from ..lifecycle.discovery import port_has_listener

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..lifecycle import PortReservation

__all__ = [
    "SCRATCH_ROLE",
    "PortAllocationError",
    "allocate_free_ports",
    "free_port",
    "hold_for_process_lifetime",
    "reserve_scratch_ports",
    "reserved_port",
]

SCRATCH_ROLE = "scratch"

# MEASURED on a Windows 11 host, 50 calls each: a connect to a port a real
# listener holds is ACCEPTED in ~3.4 ms, while a connect to an unheld loopback
# port does NOT get a prompt refusal - it runs the full budget and reports "no
# listener" by TIMING OUT. So this constant is the per-probe cost of the common
# (free) case, not a rarely-hit ceiling.
#
# Kept at 0.25 s deliberately rather than tuned down. The margin over a real
# listener's 3.4 ms answer is ~70x, and the failure mode of being too impatient
# is the exact bug the confirmation exists to fix: declaring an occupied port
# free and handing it to a child. Production's own ``_port_is_free`` is more
# patient still (0.5 s). Wall-clock is the cheaper thing to spend here.
_PORT_PROBE_TIMEOUT = 0.25
_PORT_ATTEMPTS = 20


class PortAllocationError(AssertionError):
    """No unoccupied port could be obtained for the caller."""


@contextlib.contextmanager
def reserved_port(
    *, home: Path | None = None, config: ProcsConfig | None = None
) -> Iterator[int]:
    """Hold an exclusively-reserved scratch-band port while the caller uses it.

    The reservation marker stays held for the body's duration and is released
    on exit, so the port cannot be handed to any other registry-aware claimant
    while the test binds it. ``home``/``config`` injection exists for the
    framework's own isolation tests; ordinary callers take the machine-global
    default so exclusion spans every concurrent session on the host.
    """
    resolved = config if config is not None else load_procs_config()
    reservation = reserve_port(
        SCRATCH_ROLE, resolved.role(SCRATCH_ROLE), home=home, config=resolved
    )
    try:
        yield reservation.port
    finally:
        release_reservation(reservation)


def free_port() -> int:
    """Return a loopback port with no listener answering on it.

    Default-safe: the port comes from a registry reservation over the scratch
    band, held for this process's lifetime, so a concurrent test session, a
    parallel agent, or a lifecycle boot can never be handed the same number
    while this process lives. :func:`allocate_free_ports` is the FALLBACK for a
    missing config or an exhausted band, not the primary path.

    A test wanting a claim scoped to a context rather than the process takes
    :func:`reserved_port` instead.
    """
    reservations = reserve_scratch_ports(1)
    if reservations is None:
        return allocate_free_ports(1)[0]
    hold_for_process_lifetime(reservations[0])
    return reservations[0].port


def reserve_scratch_ports(count: int) -> list[PortReservation] | None:
    """*count* registry reservations from the scratch band, or ``None``.

    ``None`` - never an exception - when the committed band config is
    unavailable or the band is exhausted, so every caller degrades to
    :func:`allocate_free_ports` instead of failing a run over allocation
    policy. Callers own what they take: release each reservation, or hand it to
    :func:`hold_for_process_lifetime`.
    """
    from ..lifecycle import ProcsConfigError

    try:
        config = load_procs_config()
        role = config.role(SCRATCH_ROLE)
    except ProcsConfigError:
        return None
    reservations: list[PortReservation] = []
    try:
        for _ in range(count):
            reservations.append(reserve_port(SCRATCH_ROLE, role, config=config))
    except (RuntimeError, OSError):
        for reservation in reservations:
            release_reservation(reservation)
        return None
    return reservations


def allocate_free_ports(count: int) -> list[int]:
    """Allocate *count* DISTINCT unoccupied loopback ports in one go (fallback).

    Every socket is bound before any is released, so the kernel cannot issue the
    same number twice within one call. Allocating in sequence instead can: the
    first port is released before the second is requested, and a measured
    200-call sample re-issued a number twice. A gateway told to serve its worker
    on its own port dies on the second bind.

    Bind-to-port-zero ALONE is not a free-port test on Windows: without
    ``SO_EXCLUSIVEADDRUSE`` a plain ``bind`` to a port another process already
    serves on ``0.0.0.0`` SUCCEEDS, so each kernel choice is confirmed with
    ``lifecycle.discovery.port_has_listener`` - the same connect probe
    production trusts - while the binding is still held (this socket never
    listens, so an ACCEPTED connect can only be a foreign listener). The
    result is still a candidate that nothing reserves, which is why the
    reservation path is the primary and this the fallback.
    """
    for _ in range(_PORT_ATTEMPTS):
        with contextlib.ExitStack() as stack:
            candidates: list[int] = []
            for _slot in range(count):
                sock = stack.enter_context(
                    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                )
                sock.bind(("127.0.0.1", 0))
                candidates.append(int(sock.getsockname()[1]))
            occupied = any(
                port_has_listener(port, timeout=_PORT_PROBE_TIMEOUT)
                for port in candidates
            )
        if not occupied:
            return candidates
    raise PortAllocationError(
        f"no {count} unoccupied loopback port(s) after {_PORT_ATTEMPTS} ephemeral "
        "allocations; every candidate already had a listener answering on it"
    )


# Scratch-band reservations held by this process. A standalone ``free_port``
# caller gives no teardown moment, so its reservation is held for the process
# lifetime and tidied at exit; a holder that dies untidily is reclaimed by the
# registry's pid-death rule regardless, so a crashed run never wedges the band.
#
# Held markers are HEARTBEATED: registry reservation liveness treats a marker
# older than its TTL (five minutes) as reclaimable regardless of pid, and a
# full suite runs far longer than that, so an unrefreshed hold would silently
# decay back to bind-probe behaviour mid-run - a late-binding worker could
# find its promised port taken, and a never-binding negative-test port could
# be claimed and bound under the test. One daemon thread touches every held
# marker's mtime well inside the TTL, making "held for the process lifetime"
# actually true.
_HELD_RESERVATIONS: list[PortReservation] = []
_HELD_LOCK = threading.Lock()
_HOLD_REFRESH_INTERVAL_S = 60.0
_HOLD_REFRESH_STOP: threading.Event | None = None


def _refresh_held_markers_once() -> None:
    """Touch every held marker's mtime; missing files are tolerated."""
    with _HELD_LOCK:
        paths = [reservation.path for reservation in _HELD_RESERVATIONS]
    for path in paths:
        with contextlib.suppress(OSError):
            os.utime(path)


def _release_held_reservations() -> None:
    stop = _HOLD_REFRESH_STOP
    if stop is not None:
        stop.set()
    while _HELD_RESERVATIONS:
        release_reservation(_HELD_RESERVATIONS.pop())


def hold_for_process_lifetime(reservation: PortReservation) -> None:
    """Keep *reservation* claimed until the process exits, heartbeating it.

    Takes over ownership: the caller must not release the reservation itself.
    """
    global _HOLD_REFRESH_STOP
    if _HOLD_REFRESH_STOP is None:
        stop = threading.Event()
        _HOLD_REFRESH_STOP = stop

        def _refresh_loop() -> None:
            while not stop.wait(_HOLD_REFRESH_INTERVAL_S):
                _refresh_held_markers_once()

        threading.Thread(
            target=_refresh_loop, name="held-reservation-refresh", daemon=True
        ).start()
        atexit.register(_release_held_reservations)
    with _HELD_LOCK:
        _HELD_RESERVATIONS.append(reservation)
