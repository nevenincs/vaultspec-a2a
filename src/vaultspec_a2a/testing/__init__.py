"""Resource-aware test execution.

The suite's contention machinery: a machine-readable resource vocabulary
(``resources``), machine-global leases arbitrating exclusive use across
processes and sessions (``leases``), progress-based deadlines that fail on
death or stall rather than on elapsed wall clock (``progress``), registry-
backed service endpoint resolution (``endpoints``), and the pytest plugin
(``plugin``) that derives scheduling groups, timeout backstops, and lease
acquisition from the declarations. The ACP test peer (``acp``) is the simulated
agent side of the protocol over stdio, with the frame reader a client-side test
uses against it.

The plugin is loaded by the repository-root ``conftest.py``, which is the one
channel that neither an ``addopts`` override can strip nor a consumer
environment can inherit; importing this facade does not register it. Public
names resolve lazily so the contained runner can declare its test environment
before any test-only import reaches the eager settings singleton.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .acp import (
        ACP_SIMULATOR_PATH,
        read_acp_frame,
        request_permission_request,
        simulator_command,
    )
    from .children import (
        DEFAULT_IDLE_WINDOW_S,
        await_child,
        child_tree_progress,
        file_size_fingerprint,
        measured_child_startup_s,
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
    from .session_root import session_scratch_dir
    from .sessions import (
        SESSION_LEASE_KEY,
        effective_worker_count,
        live_peer_sessions,
        machine_cpu_budget,
        register_session,
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
    "ACP_SIMULATOR_PATH": ("vaultspec_a2a.testing.acp", "ACP_SIMULATOR_PATH"),
    "read_acp_frame": ("vaultspec_a2a.testing.acp", "read_acp_frame"),
    "request_permission_request": (
        "vaultspec_a2a.testing.acp",
        "request_permission_request",
    ),
    "simulator_command": ("vaultspec_a2a.testing.acp", "simulator_command"),
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
    "ACP_SIMULATOR_PATH",
    "CPU_BUDGET_ENV",
    "DEFAULT_IDLE_WINDOW_S",
    "IMPURE_FIXTURES",
    "LEASE_TTL_MS",
    "MARKER_NAME",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "SCRATCH_ROLE",
    "SERVICE_MARKER",
    "SESSION_LEASE_KEY",
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
    "allocate_free_ports",
    "apply_layer_markers",
    "armed_desktop_app_home",
    "armed_environment",
    "await_child",
    "child_tree_progress",
    "declared_claims",
    "effective_worker_count",
    "exclusive_keys",
    "file_size_fingerprint",
    "forfeits_purity",
    "free_port",
    "hold_for_process_lifetime",
    "hold_lease",
    "lease_home",
    "live_peer_sessions",
    "machine_cpu_budget",
    "measured_child_startup_s",
    "plant_link_to_file",
    "read_acp_frame",
    "register_session",
    "registry_watch",
    "request_permission_request",
    "reserve_scratch_ports",
    "reserved_port",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_spec",
    "resolve_worker_url",
    "run_child",
    "session_scratch_dir",
    "settings_override",
    "simulator_command",
    "uses_impure_fixture",
    "wait_for",
]
