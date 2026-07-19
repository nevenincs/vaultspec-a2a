"""Manage development processes and gateway-restart reconciliation.

Configuration, registration, the registry, and reconciliation support
lifecycle verbs for machine-global local services.

:mod:`vaultspec_a2a.lifecycle.reconciliation` also computes pure recovery
actions for non-terminal :mod:`vaultspec_a2a.thread` state after a gateway
restart. It doesn't perform database or other input/output operations.

:mod:`vaultspec_a2a.lifecycle.procs_config` defines process configuration.
:mod:`vaultspec_a2a.lifecycle.registration` registers process definitions.
:mod:`vaultspec_a2a.lifecycle.registry` persists process state.
:mod:`vaultspec_a2a.lifecycle.manager` performs lifecycle operations.

The process commands in :mod:`vaultspec_a2a.cli` use this package. See
:ref:`process-registry` for operator guidance.
"""

from .manager import (
    LifecycleError,
    ProcVerdict,
    attach,
    default_owner,
    endpoint_for,
    kill,
    list_verdicts,
    reap,
    rebuild,
    render_command,
    render_env,
    rerun,
    resolve,
    resume,
    serve_up,
    spawn,
    tree_kill,
)
from .procs_config import (
    PortBand,
    ProcsConfig,
    ProcsConfigError,
    RoleConfig,
    load_procs_config,
    procs_config_path,
)
from .reconciliation import ReconciliationAction, compute_reconciliation_actions
from .registration import deregister_serve, refresh_registration, register_serve
from .registry import (
    PortReservation,
    ProcRecord,
    RegistryOwnershipError,
    StalenessState,
    allocate_port,
    classify_record,
    commit_reservation,
    list_records,
    now_ms,
    procs_home,
    read_record,
    record_path,
    refresh_last_seen,
    release_reservation,
    remove_record,
    remove_record_if_owned,
    reserve_port,
    write_record,
)

__all__ = [
    "LifecycleError",
    "PortBand",
    "PortReservation",
    "ProcRecord",
    "ProcVerdict",
    "ProcsConfig",
    "ProcsConfigError",
    "ReconciliationAction",
    "RegistryOwnershipError",
    "RoleConfig",
    "StalenessState",
    "allocate_port",
    "attach",
    "classify_record",
    "commit_reservation",
    "compute_reconciliation_actions",
    "default_owner",
    "deregister_serve",
    "endpoint_for",
    "kill",
    "list_records",
    "list_verdicts",
    "load_procs_config",
    "now_ms",
    "procs_config_path",
    "procs_home",
    "read_record",
    "reap",
    "rebuild",
    "record_path",
    "refresh_last_seen",
    "refresh_registration",
    "register_serve",
    "release_reservation",
    "remove_record",
    "remove_record_if_owned",
    "render_command",
    "render_env",
    "rerun",
    "reserve_port",
    "resolve",
    "resume",
    "serve_up",
    "spawn",
    "tree_kill",
    "write_record",
]
