"""Gateway <-> worker dispatch pairing verification (the campaign master-bug guard).

A procs-managed dev gateway (registered on a gateway-dev band port) must dispatch to
its paired dev worker, not silently to the owner's resident worker on the default
port; :func:`verify_dispatch_pairing` classifies the gateway's resolved
``worker_url`` against the worker-dev band and the live registry, so a mis-paired
gateway fails loud at boot instead of running green while dispatching into a foreign
stack.

The reverse direction had no guard at all: a procs-managed dev worker (registered on
a worker-dev band port) auto-derives its heartbeat target from the SAME resident
default (port 18000) when no explicit gateway URL was configured, and nothing ever
told it a paired dev gateway was live elsewhere. :func:`resolve_worker_gateway_target`
closes that gap - it lets an unconfigured band worker LEARN the live band gateway
instead of silently heartbeating the resident default forever, and refuses to boot
(mirroring the gateway-side guard) when the pairing cannot be resolved safely.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..control.config import GATEWAY_URL_ENV, WORKER_URL_ENV
from .discovery import is_pid_alive
from .procs_config import ProcsConfigError, load_procs_config
from .registry import list_records

if TYPE_CHECKING:
    from pathlib import Path

    from .procs_config import ProcsConfig

__all__ = [
    "DispatchPairingStatus",
    "WorkerPairingVerdict",
    "classify_worker_pairing",
    "eviction_is_authorized",
    "resolve_worker_gateway_target",
    "verify_dispatch_pairing",
]

_GATEWAY_ROLE = "gateway-dev"
_WORKER_ROLE = "worker-dev"


class DispatchPairingStatus(StrEnum):
    """A band gateway's dispatch-target verdict against the worker-dev band."""

    OK = "ok"  # targets a band worker port, or nothing to check
    MISPAIRED = "mispaired"  # out-of-band target + a live band worker -> refuse
    UNPAIRED = "unpaired"  # out-of-band target, no band worker -> warn only


def _worker_port(worker_url: str) -> int | None:
    try:
        return urlparse(worker_url).port
    except ValueError:
        return None


def verify_dispatch_pairing(
    worker_url: str,
    gateway_port: int,
    *,
    home: Path | None = None,
    config: ProcsConfig | None = None,
) -> tuple[DispatchPairingStatus, str]:
    """Classify a band gateway's dispatch target against the worker-dev band.

    Computes condition (a) - "is this a band dev gateway" - from *gateway_port* vs
    the gateway-dev band, so the caller can run this BEFORE self-registration and
    refuse with zero registry residue. A resident/out-of-band gateway is exempt.

    ``OK`` when the gateway is out-of-band, dispatches to a worker-dev band port, or
    there is nothing to check (missing role, unparseable url). ``MISPAIRED`` when a
    band gateway targets a port OUTSIDE the worker band while a LIVE band worker
    record exists (the master-bug misconfiguration; the caller must refuse to boot).
    ``UNPAIRED`` when a band gateway targets outside the band and no live band worker
    is running (plausible dev intent - warn only). The message is operator-actionable.
    """
    resolved_config = config
    if resolved_config is None:
        try:
            resolved_config = load_procs_config()
        except ProcsConfigError:
            return DispatchPairingStatus.OK, ""
    gateway_role = resolved_config.roles.get(_GATEWAY_ROLE)
    if gateway_role is None or gateway_port not in gateway_role.band:
        return DispatchPairingStatus.OK, ""
    worker_role = resolved_config.roles.get(_WORKER_ROLE)
    if worker_role is None:
        return DispatchPairingStatus.OK, ""

    port = _worker_port(worker_url)
    band = worker_role.band
    if port is None or port in band:
        return DispatchPairingStatus.OK, ""

    band_range = f"[{band.start}, {band.end}]"
    band_workers = [
        rec
        for rec in list_records(home)
        if rec.role == _WORKER_ROLE and rec.port in band and is_pid_alive(rec.pid)
    ]
    if band_workers:
        rec = band_workers[0]
        message = (
            f"gateway dispatch target {worker_url!r} (port {port}) is OUTSIDE the "
            f"worker-dev band {band_range}, but a live band worker is registered "
            f"({rec.role}-{rec.name} on port {rec.port}, pid {rec.pid}). Refusing to "
            "boot rather than dispatch into a foreign worker. Fix: point the gateway "
            f"at the band worker (procs up --worker-url http://127.0.0.1:{rec.port}, "
            f"or set {WORKER_URL_ENV}), or kill the band worker record if it is stale "
            f"(procs kill {rec.name})."
        )
        return DispatchPairingStatus.MISPAIRED, message

    message = (
        f"gateway dispatch target {worker_url!r} (port {port}) is outside the "
        f"worker-dev band {band_range} and no live band worker is registered - "
        "dispatching to a non-band worker; ensure this is intentional."
    )
    return DispatchPairingStatus.UNPAIRED, message


def _gateway_port(gateway_url: str) -> int | None:
    try:
        return urlparse(gateway_url).port
    except ValueError:
        return None


def resolve_worker_gateway_target(
    gateway_url: str,
    *,
    gateway_url_explicit: bool,
    worker_port: int,
    home: Path | None = None,
    config: ProcsConfig | None = None,
) -> tuple[str, DispatchPairingStatus, str]:
    """Resolve the gateway URL a band worker should heartbeat to.

    Mirrors :func:`verify_dispatch_pairing` for the worker -> gateway direction,
    plus the one behaviour the gateway side never needed: an unconfigured band
    worker LEARNS a live band gateway instead of running forever against the
    auto-derived resident default (the reported bug - a worker started against
    a live dev gateway on 18100 kept heartbeating the resident 18000).

    Returns ``(effective_gateway_url, status, message)``:

    - Not a worker-dev band port, no ``gateway-dev`` role declared, or the target
      already resolves inside the gateway-dev band: ``OK`` pass-through, the input
      URL unchanged, no message.
    - Not explicitly configured (the auto-derived resident default) and exactly one
      live band gateway is registered: ``OK`` with the LEARNED URL and an
      informational message - the worker adopts the band gateway instead of the
      resident default.
    - Not explicitly configured and zero live band gateways are registered: the
      input URL unchanged, ``UNPAIRED`` (warn-only) - a worker legitimately started
      before its gateway has nothing to pair to yet.
    - Explicitly configured (operator or spawning gateway intent) but resolves
      outside the band while a DIFFERENT live band gateway is registered, or the
      auto-derived default cannot be resolved unambiguously (more than one live
      band gateway): the input URL unchanged, ``MISPAIRED`` - refuse to boot rather
      than silently heartbeat a dead or foreign gateway.
    """
    resolved_config = config
    if resolved_config is None:
        try:
            resolved_config = load_procs_config()
        except ProcsConfigError:
            return gateway_url, DispatchPairingStatus.OK, ""
    worker_role = resolved_config.roles.get(_WORKER_ROLE)
    if worker_role is None or worker_port not in worker_role.band:
        return gateway_url, DispatchPairingStatus.OK, ""
    gateway_role = resolved_config.roles.get(_GATEWAY_ROLE)
    if gateway_role is None:
        return gateway_url, DispatchPairingStatus.OK, ""

    port = _gateway_port(gateway_url)
    band = gateway_role.band
    if port is None or port in band:
        return gateway_url, DispatchPairingStatus.OK, ""

    band_range = f"[{band.start}, {band.end}]"
    band_gateways = [
        rec
        for rec in list_records(home)
        if rec.role == _GATEWAY_ROLE and rec.port in band and is_pid_alive(rec.pid)
    ]

    if gateway_url_explicit:
        if band_gateways:
            rec = band_gateways[0]
            message = (
                f"worker gateway target {gateway_url!r} is OUTSIDE the gateway-dev "
                f"band {band_range}, but a live band gateway is registered "
                f"({rec.role}-{rec.name} on port {rec.port}, pid {rec.pid}). "
                "Refusing to boot rather than heartbeat a foreign or dead gateway. "
                f"Fix: point the worker at the band gateway (procs up --gateway-url "
                f"http://127.0.0.1:{rec.port}, or set {GATEWAY_URL_ENV})."
            )
            return gateway_url, DispatchPairingStatus.MISPAIRED, message
        message = (
            f"worker gateway target {gateway_url!r} is outside the gateway-dev "
            f"band {band_range} and no live band gateway is registered - "
            "heartbeating a non-band gateway; ensure this is intentional."
        )
        return gateway_url, DispatchPairingStatus.UNPAIRED, message

    if len(band_gateways) == 1:
        rec = band_gateways[0]
        learned = f"http://127.0.0.1:{rec.port}"
        message = (
            f"worker gateway target auto-derived to the resident default "
            f"{gateway_url!r}; learned the live band gateway instead "
            f"({rec.role}-{rec.name} on port {rec.port}, pid {rec.pid})."
        )
        return learned, DispatchPairingStatus.OK, message

    if len(band_gateways) > 1:
        names = ", ".join(f"{rec.role}-{rec.name}:{rec.port}" for rec in band_gateways)
        message = (
            f"worker gateway target defaulted to {gateway_url!r} (outside the "
            f"gateway-dev band {band_range}) and MULTIPLE live band gateways are "
            f"registered ({names}) - cannot safely pick one. Refusing to boot; set "
            f"{GATEWAY_URL_ENV} explicitly (procs up --gateway-url ...)."
        )
        return gateway_url, DispatchPairingStatus.MISPAIRED, message

    message = (
        f"worker gateway target defaulted to {gateway_url!r} (outside the "
        f"gateway-dev band {band_range}) and no live band gateway is registered "
        "yet - heartbeating the resident default until one appears; ensure this "
        "is intentional."
    )
    return gateway_url, DispatchPairingStatus.UNPAIRED, message


class WorkerPairingVerdict(StrEnum):
    """What a worker's reported identity licenses this gateway to do."""

    OWNED = "owned"
    """This gateway's current generation: adopt and dispatch."""

    PRIOR_GENERATION = "prior_generation"
    """This gateway spawned it, but an earlier attempt did: evictable by the owner."""

    FOREIGN = "foreign"
    """Another gateway incarnation spawned it: never adopt, never evict."""

    UNIDENTIFIED = "unidentified"
    """No usable pairing evidence: never adopt, never evict."""


def classify_worker_pairing(
    *,
    reported_lifetime: str | None,
    reported_generation: str | None,
    gateway_lifetime: str,
    current_generation: int,
) -> WorkerPairingVerdict:
    """Classify a worker's claimed pairing against this gateway's identity.

    Fails closed on every ambiguity. Blank evidence is ``UNIDENTIFIED`` rather
    than assumed-ours, because a worker that reports nothing is exactly what a
    process this gateway never started looks like - Compose, an operator, a test,
    or another gateway's orphan. Treating silence as ownership is how dispatch
    reached a foreign worker.

    A generation that does not parse, or that claims to be newer than any this
    gateway has issued, is also ``UNIDENTIFIED``: a worker cannot legitimately
    hold a generation its gateway never minted, so the claim is evidence the
    record is wrong rather than evidence of a newer worker.

    Args:
        reported_lifetime: The gateway lifetime the worker says spawned it.
        reported_generation: The spawn generation the worker says it belongs to.
        gateway_lifetime: This gateway process's own lifetime identity.
        current_generation: The highest generation this gateway has issued.

    Returns:
        The verdict governing adoption and eviction.
    """
    if not reported_lifetime or not reported_lifetime.strip():
        return WorkerPairingVerdict.UNIDENTIFIED
    if reported_lifetime.strip() != gateway_lifetime:
        return WorkerPairingVerdict.FOREIGN
    if reported_generation is None or not reported_generation.strip():
        return WorkerPairingVerdict.UNIDENTIFIED
    try:
        generation = int(reported_generation.strip())
    except ValueError:
        return WorkerPairingVerdict.UNIDENTIFIED
    if generation <= 0 or generation > current_generation:
        return WorkerPairingVerdict.UNIDENTIFIED
    if generation < current_generation:
        return WorkerPairingVerdict.PRIOR_GENERATION
    return WorkerPairingVerdict.OWNED


def eviction_is_authorized(
    verdict: WorkerPairingVerdict, *, desktop_profile_armed: bool
) -> bool:
    """Return whether this gateway may terminate the worker it just classified.

    Eviction is a hard kill of another process, so it is permitted in exactly one
    case: an armed desktop gateway reclaiming a worker it demonstrably spawned
    under an earlier generation. Every other verdict refuses.

    A foreign worker is never evicted even though it is in the way, because the
    gateway that owns it may be serving live runs. An unidentified worker is
    never evicted because absence of evidence is not evidence of ownership. An
    owned current-generation worker is not evicted because it is the one in use.
    """
    return desktop_profile_armed and verdict is WorkerPairingVerdict.PRIOR_GENERATION
