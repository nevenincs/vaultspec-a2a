"""Gateway -> worker dispatch pairing verification (the campaign master-bug guard).

A procs-managed dev gateway (registered on a gateway-dev band port) must dispatch to
its paired dev worker, not silently to the owner's resident worker on the default
port. This classifies the gateway's resolved ``worker_url`` against the worker-dev
band and the live registry, so a mis-paired gateway fails loud at boot instead of
running green while dispatching into a foreign stack.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..control.config import WORKER_URL_ENV
from .discovery import is_pid_alive
from .procs_config import ProcsConfigError, load_procs_config
from .registry import list_records

if TYPE_CHECKING:
    from pathlib import Path

    from .procs_config import ProcsConfig

__all__ = ["DispatchPairingStatus", "verify_dispatch_pairing"]

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
    worker_url: str, *, home: Path | None = None, config: ProcsConfig | None = None
) -> tuple[DispatchPairingStatus, str]:
    """Classify a band gateway's dispatch target against the worker-dev band.

    ``OK`` when the gateway dispatches to a worker-dev band port (or there is nothing
    to check - no worker-dev role, or an unparseable url). ``MISPAIRED`` when it
    targets a port OUTSIDE the band while a live band worker record exists (the
    master-bug misconfiguration; the caller must refuse to boot). ``UNPAIRED`` when it
    targets outside the band and no band worker is running (plausible dev intent -
    warn only). The returned message is operator-actionable.
    """
    resolved_config = config
    if resolved_config is None:
        try:
            resolved_config = load_procs_config()
        except ProcsConfigError:
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
