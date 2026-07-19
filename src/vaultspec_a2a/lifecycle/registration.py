"""Serve-path adoption of the dev-process registry.

A serve entry point - the gateway, the worker, the engine-serve wrapper - calls
:func:`register_serve` on startup and :func:`deregister_serve` on owned shutdown,
so a dev/test instance booted on a role band port becomes enumerable, attachable,
and reapable through the ``procs`` verbs. A RESIDENT instance on its fixed
out-of-band port (gateway 18000, engine 8767) registers nothing - ``register_serve``
returns ``None`` when the port is not inside the role's band - so production
behaviour is unchanged and the "resident instances are never managed" rule
holds by construction rather than by a config flag.

For a heartbeating role the serve path refreshes the record via
:func:`refresh_registration` on its existing heartbeat cadence, so a live dev
instance never drifts to STALE and gets reaped out from under itself.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import TYPE_CHECKING

from .procs_config import ProcsConfigError, load_procs_config
from .registry import (
    NAME_ENV,
    ProcRecord,
    RegistryOwnershipError,
    now_ms,
    read_record,
    record_path,
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

    resolved_name = name or os.environ.get(NAME_ENV) or str(port)
    resolved_owner = owner if owner is not None else default_owner()
    stamp = now_ms()
    existing = read_record(record_path(role, resolved_name, home=home))
    if existing is not None:
        # Convergence: a self-registering child (booted by serve_up) meets the
        # record serve_up already committed. Self-registration owns only the runtime
        # identity - pid, command, owner, heartbeat - so every operator-supplied
        # field (log_path, repo, build_repo, workspace, build_sha,
        # engine_service_json, internal_token_file, gateway_url, started_at_ms) is
        # PRESERVED, never reset to a default. Clobbering log_path here once left
        # gateway/worker logs dead mid-incident.
        record = replace(
            existing,
            pid=os.getpid(),
            command=list(command) if command else existing.command,
            owner=resolved_owner,
            last_seen_ms=stamp,
        )
    else:
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
            owner=resolved_owner,
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
    """Advance a registered record's heartbeat; a no-op when nothing was registered.

    Re-reads the CURRENT on-disk record before bumping the heartbeat, so a richer
    record that landed AFTER this process's own registration is preserved rather
    than overwritten by this process's staler in-memory copy on every cadence.
    During boot a self-registering gateway/worker calls ``register_serve`` before
    ``serve_up`` commits the full operator-supplied record (the reservation race),
    so its in-memory ``record`` can be a defaults-only one; heartbeating that copy
    is what silently blanked log_path and the pairing fields mid-run. Reading the
    live record first makes the heartbeat non-destructive.
    """
    if record is None:
        return
    current = read_record(record_path(record.role, record.name, home=home))
    refresh_last_seen(current if current is not None else record, home=home)


def deregister_serve(record: ProcRecord | None, *, home: Path | None = None) -> None:
    """Drop a registered record on owned shutdown; a no-op when nothing registered."""
    if record is not None:
        remove_record_if_owned(record.role, record.name, record.owner, home=home)
