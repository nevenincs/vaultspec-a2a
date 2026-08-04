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
environment can inherit; importing this facade does not register it.
"""

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
from .leases import (
    LEASE_TTL_MS,
    Lease,
    LeaseAcquisitionTimeoutError,
    hold_lease,
    lease_home,
)
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
from .sessions import (
    CPU_BUDGET_ENV,
    SESSION_LEASE_KEY,
    effective_worker_count,
    live_peer_sessions,
    machine_cpu_budget,
    register_session,
)

__all__ = [
    "CPU_BUDGET_ENV",
    "LEASE_TTL_MS",
    "MARKER_NAME",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "SCRATCH_ROLE",
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
    "armed_desktop_app_home",
    "armed_environment",
    "declared_claims",
    "effective_worker_count",
    "exclusive_keys",
    "free_port",
    "hold_for_process_lifetime",
    "hold_lease",
    "lease_home",
    "live_peer_sessions",
    "machine_cpu_budget",
    "register_session",
    "registry_watch",
    "reserve_scratch_ports",
    "reserved_port",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_spec",
    "resolve_worker_url",
    "settings_override",
    "wait_for",
]
