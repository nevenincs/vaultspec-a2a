"""Resource-aware test execution.

The suite's contention machinery: a machine-readable resource vocabulary
(``resources``), machine-global leases arbitrating exclusive use across
processes and sessions (``leases``), progress-based deadlines that fail on
death or stall rather than on elapsed wall clock (``progress``), registry-
backed service endpoint resolution (``endpoints``), and the pytest plugin
(``plugin``) that derives scheduling groups, timeout backstops, and lease
acquisition from the declarations.

The plugin is loaded by the repository-root ``conftest.py``, which is the one
channel that neither an ``addopts`` override can strip nor a consumer
environment can inherit; importing this facade does not register it. Public
names resolve lazily so the contained runner can declare its test environment
before any test-only import reaches the eager settings singleton.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


_LAZY_EXPORTS = {
    "ResolvedService": (".endpoints", "ResolvedService"),
    "resolve_gateway_url": (".endpoints", "resolve_gateway_url"),
    "resolve_service": (".endpoints", "resolve_service"),
    "resolve_worker_url": (".endpoints", "resolve_worker_url"),
    "armed_desktop_app_home": (".environment", "armed_desktop_app_home"),
    "session_scratch_dir": (".session_root", "session_scratch_dir"),
    "armed_environment": (".environment", "armed_environment"),
    "settings_override": (".environment", "settings_override"),
    "LEASE_TTL_MS": (".leases", "LEASE_TTL_MS"),
    "Lease": (".leases", "Lease"),
    "LeaseAcquisitionTimeoutError": (
        ".leases",
        "LeaseAcquisitionTimeoutError",
    ),
    "hold_lease": (".leases", "hold_lease"),
    "lease_home": (".leases", "lease_home"),
    "plant_link_to_file": (".links", "plant_link_to_file"),
    "apply_layer_markers": (".markers", "apply_layer_markers"),
    "SCRATCH_ROLE": (".ports", "SCRATCH_ROLE"),
    "PortAllocationError": (".ports", "PortAllocationError"),
    "allocate_free_ports": (".ports", "allocate_free_ports"),
    "free_port": (".ports", "free_port"),
    "hold_for_process_lifetime": (".ports", "hold_for_process_lifetime"),
    "reserve_scratch_ports": (".ports", "reserve_scratch_ports"),
    "reserved_port": (".ports", "reserved_port"),
    "LivenessWatch": (".progress", "LivenessWatch"),
    "ProgressDeadline": (".progress", "ProgressDeadline"),
    "ProgressStalledError": (".progress", "ProgressStalledError"),
    "ResourceDiedError": (".progress", "ResourceDiedError"),
    "registry_watch": (".progress", "registry_watch"),
    "wait_for": (".progress", "wait_for"),
    "IMPURE_FIXTURES": (".purity", "IMPURE_FIXTURES"),
    "SERVICE_MARKER": (".purity", "SERVICE_MARKER"),
    "forfeits_purity": (".purity", "forfeits_purity"),
    "uses_impure_fixture": (".purity", "uses_impure_fixture"),
    "MARKER_NAME": (".resources", "MARKER_NAME"),
    "RESOURCES": (".resources", "RESOURCES"),
    "SCRATCH_PREFIX": (".resources", "SCRATCH_PREFIX"),
    "ResourceClaim": (".resources", "ResourceClaim"),
    "ResourceDeclarationError": (".resources", "ResourceDeclarationError"),
    "ResourceSpec": (".resources", "ResourceSpec"),
    "declared_claims": (".resources", "declared_claims"),
    "exclusive_keys": (".resources", "exclusive_keys"),
    "resolve_spec": (".resources", "resolve_spec"),
    "CPU_BUDGET_ENV": (".harness_names", "CPU_BUDGET_ENV"),
    "SESSION_LEASE_KEY": (".sessions", "SESSION_LEASE_KEY"),
    "effective_worker_count": (".sessions", "effective_worker_count"),
    "live_peer_sessions": (".sessions", "live_peer_sessions"),
    "machine_cpu_budget": (".sessions", "machine_cpu_budget"),
    "register_session": (".sessions", "register_session"),
}


def __getattr__(name: str) -> object:
    """Resolve a facade export only when a caller actually uses it."""
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public names to introspection without importing them."""
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "CPU_BUDGET_ENV",
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
    "declared_claims",
    "effective_worker_count",
    "exclusive_keys",
    "forfeits_purity",
    "free_port",
    "hold_for_process_lifetime",
    "hold_lease",
    "lease_home",
    "live_peer_sessions",
    "machine_cpu_budget",
    "plant_link_to_file",
    "register_session",
    "registry_watch",
    "reserve_scratch_ports",
    "reserved_port",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_spec",
    "resolve_worker_url",
    "session_scratch_dir",
    "settings_override",
    "uses_impure_fixture",
    "wait_for",
]
