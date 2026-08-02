"""Resource-aware test execution.

The suite's contention machinery: a machine-readable resource vocabulary
(``resources``), machine-global leases arbitrating exclusive use across
processes and sessions (``leases``), progress-based deadlines that fail on
death or stall rather than on elapsed wall clock (``progress``), registry-
backed service endpoint resolution (``endpoints``), and the pytest plugin
(``plugin``) that derives scheduling groups, timeout backstops, and lease
acquisition from the declarations.

The plugin is loaded through the ``-p vaultspec_a2a.testing.plugin`` entry in
the suite's configured ``addopts``; importing this facade does not register it.
"""

from .endpoints import (
    ResolvedService,
    resolve_gateway_url,
    resolve_service,
    resolve_worker_url,
)
from .leases import (
    LEASE_TTL_MS,
    Lease,
    LeaseAcquisitionTimeoutError,
    hold_lease,
    lease_home,
)
from .ports import SCRATCH_ROLE, reserved_port
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

__all__ = [
    "LEASE_TTL_MS",
    "MARKER_NAME",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "SCRATCH_ROLE",
    "Lease",
    "LeaseAcquisitionTimeoutError",
    "LivenessWatch",
    "ProgressDeadline",
    "ProgressStalledError",
    "ResolvedService",
    "ResourceClaim",
    "ResourceDeclarationError",
    "ResourceDiedError",
    "ResourceSpec",
    "declared_claims",
    "exclusive_keys",
    "hold_lease",
    "lease_home",
    "registry_watch",
    "reserved_port",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_spec",
    "resolve_worker_url",
    "wait_for",
]
