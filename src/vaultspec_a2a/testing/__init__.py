"""Resource-aware test execution.

The suite's contention machinery: a machine-readable resource vocabulary
(``resources``), machine-global leases arbitrating exclusive use across
processes and sessions (``leases``), progress-based deadlines that fail on
death or stall rather than on elapsed wall clock (``progress``), registry-
backed service endpoint resolution (``endpoints``), and the pytest plugin
(``plugin``) that derives scheduling groups, timeout backstops, and lease
acquisition from the declarations. Beside it sits the real-process support every
test tier composes rather than retypes: the gateway boot and its peers
(``boot``), the loopback listeners a test points code at (``http``), and the
run-start verb shaped once (``verbs``).

The plugin is loaded by the repository-root ``conftest.py``, which is the one
channel that neither an ``addopts`` override can strip nor a consumer
environment can inherit; importing this facade does not register it. Public
names resolve lazily so the contained runner can declare its test environment
before any test-only import reaches the eager settings singleton.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .boot import (
        DEFAULT_ATTACH_CREDENTIAL,
        DEFAULT_OWNERSHIP_CAPABILITY,
        FIRST_DEMAND_TIMEOUT,
        FOREIGN_WORKER_PROGRAM,
        LOOPBACK_TIMEOUT,
        READINESS_TIMEOUT,
        BootedGateway,
        GatewayBootError,
        SignalledChild,
        WatchedProcess,
        armed_gateway_env,
        await_gateway_ready,
        await_ready,
        booted_gateway,
        broker_gateway_env,
        clean_subprocess_environment,
        desktop_workspace,
        foreign_worker,
        gateway_process_env,
        gateway_script,
        log_tail,
        loopback_callback_bridge,
        reap_process,
        seat_app_home,
        spawn_gateway,
        spawn_logged,
        spawn_signalled,
        spawn_until_ready,
        worker_lifecycle_gateway_script,
    )
    from .children import (
        DEFAULT_IDLE_WINDOW_S,
        await_child,
        child_tree_progress,
        file_size_fingerprint,
        measured_child_startup_s,
        reap_tree,
        run_child,
    )
    from .endpoints import (
        ResolvedService,
        resolve_gateway_url,
        resolve_service,
        resolve_worker_url,
    )
    from .environment import (
        armed_desktop_app_home,
        armed_environment,
        settings_override,
    )
    from .harness_names import CPU_BUDGET_ENV
    from .http import (
        JsonReplyHandler,
        health_listener,
        loopback_uvicorn,
        serve_handler,
        serve_on_loopback,
        serve_on_loopback_in_thread,
        uvicorn_started,
    )
    from .leases import (
        LEASE_TTL_MS,
        Lease,
        LeaseAcquisitionTimeoutError,
        hold_lease,
        lease_home,
    )
    from .links import plant_link_to_file
    from .markers import apply_layer_markers
    from .ports import (
        SCRATCH_ROLE,
        PortAllocationError,
        allocate_free_ports,
        free_port,
        hold_for_process_lifetime,
        reserve_scratch_ports,
        reserved_port,
    )
    from .progress import (
        LivenessWatch,
        ProgressDeadline,
        ProgressStalledError,
        ResourceDiedError,
        registry_watch,
        wait_for,
    )
    from .purity import (
        IMPURE_FIXTURES,
        SERVICE_MARKER,
        forfeits_purity,
        uses_impure_fixture,
    )
    from .resources import (
        MARKER_NAME,
        RESOURCES,
        SCRATCH_PREFIX,
        ResourceClaim,
        ResourceDeclarationError,
        ResourceSpec,
        declared_claims,
        exclusive_keys,
        resolve_spec,
    )
    from .session_root import prune_stale_dirs, session_scratch_dir
    from .sessions import (
        SESSION_LEASE_KEY,
        effective_worker_count,
        live_peer_sessions,
        machine_cpu_budget,
        register_session,
    )
    from .verbs import (
        RunVerbs,
        status_and_json,
    )


#: Fully-qualified (never relative) submodule names: this dict's string values
#: are themselves how a repository-configured surface names a shipped module by
#: dotted string rather than by import (see ``string_module_edges`` in
#: ``dev/audit/unreachable_code.py``), the same mechanism that keeps a uvicorn
#: factory or a worker process target live. A relative ``".children"`` here
#: would resolve identically at import time but would not be recognised as
#: naming ``vaultspec_a2a.testing.children``, leaving every submodule this
#: facade lazily loads misreported as reachable only through type checking.
_LAZY_EXPORTS = {
    "DEFAULT_ATTACH_CREDENTIAL": (
        "vaultspec_a2a.testing.boot",
        "DEFAULT_ATTACH_CREDENTIAL",
    ),
    "DEFAULT_OWNERSHIP_CAPABILITY": (
        "vaultspec_a2a.testing.boot",
        "DEFAULT_OWNERSHIP_CAPABILITY",
    ),
    "FIRST_DEMAND_TIMEOUT": ("vaultspec_a2a.testing.boot", "FIRST_DEMAND_TIMEOUT"),
    "FOREIGN_WORKER_PROGRAM": ("vaultspec_a2a.testing.boot", "FOREIGN_WORKER_PROGRAM"),
    "LOOPBACK_TIMEOUT": ("vaultspec_a2a.testing.boot", "LOOPBACK_TIMEOUT"),
    "READINESS_TIMEOUT": ("vaultspec_a2a.testing.boot", "READINESS_TIMEOUT"),
    "BootedGateway": ("vaultspec_a2a.testing.boot", "BootedGateway"),
    "GatewayBootError": ("vaultspec_a2a.testing.boot", "GatewayBootError"),
    "SignalledChild": ("vaultspec_a2a.testing.boot", "SignalledChild"),
    "WatchedProcess": ("vaultspec_a2a.testing.boot", "WatchedProcess"),
    "armed_gateway_env": ("vaultspec_a2a.testing.boot", "armed_gateway_env"),
    "await_gateway_ready": ("vaultspec_a2a.testing.boot", "await_gateway_ready"),
    "await_ready": ("vaultspec_a2a.testing.boot", "await_ready"),
    "booted_gateway": ("vaultspec_a2a.testing.boot", "booted_gateway"),
    "broker_gateway_env": ("vaultspec_a2a.testing.boot", "broker_gateway_env"),
    "clean_subprocess_environment": (
        "vaultspec_a2a.testing.boot",
        "clean_subprocess_environment",
    ),
    "desktop_workspace": ("vaultspec_a2a.testing.boot", "desktop_workspace"),
    "foreign_worker": ("vaultspec_a2a.testing.boot", "foreign_worker"),
    "gateway_process_env": ("vaultspec_a2a.testing.boot", "gateway_process_env"),
    "gateway_script": ("vaultspec_a2a.testing.boot", "gateway_script"),
    "log_tail": ("vaultspec_a2a.testing.boot", "log_tail"),
    "loopback_callback_bridge": (
        "vaultspec_a2a.testing.boot",
        "loopback_callback_bridge",
    ),
    "reap_process": ("vaultspec_a2a.testing.boot", "reap_process"),
    "seat_app_home": ("vaultspec_a2a.testing.boot", "seat_app_home"),
    "spawn_gateway": ("vaultspec_a2a.testing.boot", "spawn_gateway"),
    "spawn_logged": ("vaultspec_a2a.testing.boot", "spawn_logged"),
    "spawn_signalled": ("vaultspec_a2a.testing.boot", "spawn_signalled"),
    "spawn_until_ready": ("vaultspec_a2a.testing.boot", "spawn_until_ready"),
    "worker_lifecycle_gateway_script": (
        "vaultspec_a2a.testing.boot",
        "worker_lifecycle_gateway_script",
    ),
    "DEFAULT_IDLE_WINDOW_S": (
        "vaultspec_a2a.testing.children",
        "DEFAULT_IDLE_WINDOW_S",
    ),
    "await_child": ("vaultspec_a2a.testing.children", "await_child"),
    "child_tree_progress": ("vaultspec_a2a.testing.children", "child_tree_progress"),
    "file_size_fingerprint": (
        "vaultspec_a2a.testing.children",
        "file_size_fingerprint",
    ),
    "measured_child_startup_s": (
        "vaultspec_a2a.testing.children",
        "measured_child_startup_s",
    ),
    "reap_tree": ("vaultspec_a2a.testing.children", "reap_tree"),
    "run_child": ("vaultspec_a2a.testing.children", "run_child"),
    "ResolvedService": ("vaultspec_a2a.testing.endpoints", "ResolvedService"),
    "resolve_gateway_url": (
        "vaultspec_a2a.testing.endpoints",
        "resolve_gateway_url",
    ),
    "resolve_service": ("vaultspec_a2a.testing.endpoints", "resolve_service"),
    "resolve_worker_url": ("vaultspec_a2a.testing.endpoints", "resolve_worker_url"),
    "armed_desktop_app_home": (
        "vaultspec_a2a.testing.environment",
        "armed_desktop_app_home",
    ),
    "prune_stale_dirs": ("vaultspec_a2a.testing.session_root", "prune_stale_dirs"),
    "session_scratch_dir": (
        "vaultspec_a2a.testing.session_root",
        "session_scratch_dir",
    ),
    "armed_environment": ("vaultspec_a2a.testing.environment", "armed_environment"),
    "settings_override": ("vaultspec_a2a.testing.environment", "settings_override"),
    "LEASE_TTL_MS": ("vaultspec_a2a.testing.leases", "LEASE_TTL_MS"),
    "Lease": ("vaultspec_a2a.testing.leases", "Lease"),
    "LeaseAcquisitionTimeoutError": (
        "vaultspec_a2a.testing.leases",
        "LeaseAcquisitionTimeoutError",
    ),
    "hold_lease": ("vaultspec_a2a.testing.leases", "hold_lease"),
    "lease_home": ("vaultspec_a2a.testing.leases", "lease_home"),
    "plant_link_to_file": ("vaultspec_a2a.testing.links", "plant_link_to_file"),
    "apply_layer_markers": ("vaultspec_a2a.testing.markers", "apply_layer_markers"),
    "SCRATCH_ROLE": ("vaultspec_a2a.testing.ports", "SCRATCH_ROLE"),
    "PortAllocationError": ("vaultspec_a2a.testing.ports", "PortAllocationError"),
    "allocate_free_ports": ("vaultspec_a2a.testing.ports", "allocate_free_ports"),
    "free_port": ("vaultspec_a2a.testing.ports", "free_port"),
    "hold_for_process_lifetime": (
        "vaultspec_a2a.testing.ports",
        "hold_for_process_lifetime",
    ),
    "reserve_scratch_ports": (
        "vaultspec_a2a.testing.ports",
        "reserve_scratch_ports",
    ),
    "reserved_port": ("vaultspec_a2a.testing.ports", "reserved_port"),
    "LivenessWatch": ("vaultspec_a2a.testing.progress", "LivenessWatch"),
    "ProgressDeadline": ("vaultspec_a2a.testing.progress", "ProgressDeadline"),
    "ProgressStalledError": ("vaultspec_a2a.testing.progress", "ProgressStalledError"),
    "ResourceDiedError": ("vaultspec_a2a.testing.progress", "ResourceDiedError"),
    "registry_watch": ("vaultspec_a2a.testing.progress", "registry_watch"),
    "wait_for": ("vaultspec_a2a.testing.progress", "wait_for"),
    "IMPURE_FIXTURES": ("vaultspec_a2a.testing.purity", "IMPURE_FIXTURES"),
    "SERVICE_MARKER": ("vaultspec_a2a.testing.purity", "SERVICE_MARKER"),
    "forfeits_purity": ("vaultspec_a2a.testing.purity", "forfeits_purity"),
    "uses_impure_fixture": ("vaultspec_a2a.testing.purity", "uses_impure_fixture"),
    "MARKER_NAME": ("vaultspec_a2a.testing.resources", "MARKER_NAME"),
    "RESOURCES": ("vaultspec_a2a.testing.resources", "RESOURCES"),
    "SCRATCH_PREFIX": ("vaultspec_a2a.testing.resources", "SCRATCH_PREFIX"),
    "ResourceClaim": ("vaultspec_a2a.testing.resources", "ResourceClaim"),
    "ResourceDeclarationError": (
        "vaultspec_a2a.testing.resources",
        "ResourceDeclarationError",
    ),
    "ResourceSpec": ("vaultspec_a2a.testing.resources", "ResourceSpec"),
    "declared_claims": ("vaultspec_a2a.testing.resources", "declared_claims"),
    "exclusive_keys": ("vaultspec_a2a.testing.resources", "exclusive_keys"),
    "resolve_spec": ("vaultspec_a2a.testing.resources", "resolve_spec"),
    "CPU_BUDGET_ENV": ("vaultspec_a2a.testing.harness_names", "CPU_BUDGET_ENV"),
    "SESSION_LEASE_KEY": ("vaultspec_a2a.testing.sessions", "SESSION_LEASE_KEY"),
    "effective_worker_count": (
        "vaultspec_a2a.testing.sessions",
        "effective_worker_count",
    ),
    "live_peer_sessions": ("vaultspec_a2a.testing.sessions", "live_peer_sessions"),
    "machine_cpu_budget": ("vaultspec_a2a.testing.sessions", "machine_cpu_budget"),
    "register_session": ("vaultspec_a2a.testing.sessions", "register_session"),
    "JsonReplyHandler": ("vaultspec_a2a.testing.http", "JsonReplyHandler"),
    "health_listener": ("vaultspec_a2a.testing.http", "health_listener"),
    "loopback_uvicorn": ("vaultspec_a2a.testing.http", "loopback_uvicorn"),
    "serve_handler": ("vaultspec_a2a.testing.http", "serve_handler"),
    "serve_on_loopback": ("vaultspec_a2a.testing.http", "serve_on_loopback"),
    "serve_on_loopback_in_thread": (
        "vaultspec_a2a.testing.http",
        "serve_on_loopback_in_thread",
    ),
    "uvicorn_started": ("vaultspec_a2a.testing.http", "uvicorn_started"),
    "RunVerbs": ("vaultspec_a2a.testing.verbs", "RunVerbs"),
    "status_and_json": ("vaultspec_a2a.testing.verbs", "status_and_json"),
}


def __getattr__(name: str) -> object:
    """Resolve a facade export only when a caller actually uses it."""
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public names to introspection without importing them."""
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "CPU_BUDGET_ENV",
    "DEFAULT_ATTACH_CREDENTIAL",
    "DEFAULT_IDLE_WINDOW_S",
    "DEFAULT_OWNERSHIP_CAPABILITY",
    "FIRST_DEMAND_TIMEOUT",
    "FOREIGN_WORKER_PROGRAM",
    "IMPURE_FIXTURES",
    "LEASE_TTL_MS",
    "LOOPBACK_TIMEOUT",
    "MARKER_NAME",
    "READINESS_TIMEOUT",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "SCRATCH_ROLE",
    "SERVICE_MARKER",
    "SESSION_LEASE_KEY",
    "BootedGateway",
    "GatewayBootError",
    "JsonReplyHandler",
    "Lease",
    "LeaseAcquisitionTimeoutError",
    "LivenessWatch",
    "PortAllocationError",
    "ProgressDeadline",
    "ProgressStalledError",
    "ResolvedService",
    "ResourceClaim",
    "ResourceDeclarationError",
    "ResourceDiedError",
    "ResourceSpec",
    "RunVerbs",
    "SignalledChild",
    "WatchedProcess",
    "allocate_free_ports",
    "apply_layer_markers",
    "armed_desktop_app_home",
    "armed_environment",
    "armed_gateway_env",
    "await_child",
    "await_gateway_ready",
    "await_ready",
    "booted_gateway",
    "broker_gateway_env",
    "child_tree_progress",
    "clean_subprocess_environment",
    "declared_claims",
    "desktop_workspace",
    "effective_worker_count",
    "exclusive_keys",
    "file_size_fingerprint",
    "foreign_worker",
    "forfeits_purity",
    "free_port",
    "gateway_process_env",
    "gateway_script",
    "health_listener",
    "hold_for_process_lifetime",
    "hold_lease",
    "lease_home",
    "live_peer_sessions",
    "log_tail",
    "loopback_callback_bridge",
    "loopback_uvicorn",
    "machine_cpu_budget",
    "measured_child_startup_s",
    "plant_link_to_file",
    "prune_stale_dirs",
    "reap_process",
    "reap_tree",
    "register_session",
    "registry_watch",
    "reserve_scratch_ports",
    "reserved_port",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_spec",
    "resolve_worker_url",
    "run_child",
    "seat_app_home",
    "serve_handler",
    "serve_on_loopback",
    "serve_on_loopback_in_thread",
    "session_scratch_dir",
    "settings_override",
    "spawn_gateway",
    "spawn_logged",
    "spawn_signalled",
    "spawn_until_ready",
    "status_and_json",
    "uses_impure_fixture",
    "uvicorn_started",
    "wait_for",
    "worker_lifecycle_gateway_script",
]
