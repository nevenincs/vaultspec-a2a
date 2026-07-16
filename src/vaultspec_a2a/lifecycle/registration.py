"""Serve-path adoption of the dev-process registry (dev-process-registry ADR).

A serve entry point - the gateway, the worker, the engine-serve wrapper - calls
:func:`register_serve` on startup and :func:`deregister_serve` on owned shutdown,
so a dev/test instance booted on a role band port becomes enumerable, attachable,
and reapable through the ``procs`` verbs. A RESIDENT instance on its fixed
out-of-band port (gateway 8000, engine 8767) registers nothing - ``register_serve``
returns ``None`` when the port is not inside the role's band - so production
behaviour is unchanged and the ADR's "resident instances are never managed" rule
holds by construction rather than by a config flag.

For a heartbeating role the serve path refreshes the record via
:func:`refresh_registration` on its existing heartbeat cadence, so a live dev
instance never drifts to STALE and gets reaped out from under itself.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from .procs_config import ProcsConfigError, load_procs_config
from .registry import (
    ProcRecord,
    RegistryOwnershipError,
    now_ms,
    refresh_last_seen,
    remove_record_if_owned,
    write_record,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .procs_config import ProcsConfig

__all__ = [
    "deregister_serve",
    "refresh_registration",
    "register_serve",
]

logger = logging.getLogger(__name__)

_NAME_ENV = "VAULTSPEC_PROCS_NAME"


def _load_config() -> ProcsConfig | None:
    try:
        return load_procs_config()
    except ProcsConfigError:
        return None


def register_serve(
    role: str,
    port: int,
    *,
    workspace: str = "",
    repo: str = "",
    owner: str | None = None,
    name: str | None = None,
    command: list[str] | None = None,
    home: Path | None = None,
    config: ProcsConfig | None = None,
) -> ProcRecord | None:
    """Register the current process as a managed dev instance, or return ``None``.

    Returns ``None`` - registering nothing - when procs.toml is unreadable, the
    role is unknown, or *port* is not inside the role's band (a resident or
    ad-hoc port). Otherwise writes a claiming record keyed on the port (or
    ``VAULTSPEC_PROCS_NAME``) and returns it, so the caller can refresh and
    deregister it.
    """
    resolved_config = config if config is not None else _load_config()
    if resolved_config is None:
        return None
    role_cfg = resolved_config.roles.get(role)
    if role_cfg is None or port not in role_cfg.band:
        return None
    from .manager import default_owner

    resolved_name = name or os.environ.get(_NAME_ENV) or str(port)
    stamp = now_ms()
    record = ProcRecord(
        name=resolved_name,
        role=role,
        pid=os.getpid(),
        port=port,
        repo=repo,
        workspace=workspace,
        command=list(command or []),
        started_at_ms=stamp,
        last_seen_ms=stamp,
        owner=owner if owner is not None else default_owner(),
    )
    # Registration is best-effort adoption, never a boot dependency: a registry
    # hiccup (a live foreign-owned record on the band port, a full disk) must not
    # take down a serving gateway/worker, so it degrades to "unregistered" - the
    # same non-fatal stance the heartbeat refresh already takes.
    try:
        write_record(record, home=home)
    except (RegistryOwnershipError, OSError):
        logger.warning(
            "dev-process registration skipped for %s-%s on port %d",
            role,
            resolved_name,
            port,
            exc_info=True,
        )
        return None
    return record


def refresh_registration(
    record: ProcRecord | None, *, home: Path | None = None
) -> None:
    """Advance a registered record's heartbeat; a no-op when nothing was registered."""
    if record is not None:
        refresh_last_seen(record, home=home)


def deregister_serve(record: ProcRecord | None, *, home: Path | None = None) -> None:
    """Drop a registered record on owned shutdown; a no-op when nothing registered."""
    if record is not None:
        remove_record_if_owned(record.role, record.name, record.owner, home=home)
