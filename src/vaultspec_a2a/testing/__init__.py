"""Resource-aware test execution.

The suite's contention machinery: a machine-readable resource vocabulary
(``resources``), machine-global leases arbitrating exclusive use across
processes and sessions (``leases``), progress-based deadlines that fail on
death or stall rather than on elapsed wall clock (``progress``), run-status
polling built on them (``polling``), registry-backed service endpoint
resolution (``endpoints``), and the pytest plugin
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
    from .catalog import (
        LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON,
        LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON,
        LIVE_PROVIDER_PREREQUISITES,
        NoSelectableLaneError,
        async_catalog_run_fields,
        async_fetch_in_process_selection,
        async_fetch_provider_catalog,
        catalog_run_fields,
        declared_lane_model_value,
        fetch_in_process_selection,
        fetch_in_process_selection_at,
        fetch_provider_catalog,
        in_process_lane_selection,
        in_process_selection,
        live_provider_catalog_selector_is_configured,
        live_provider_override_selector_is_configured,
        named_lane_selection,
        override_selection_from_served_catalog,
        selection_from_served_catalog,
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
    from .graph import (
        add_test_node,
        ainvoke_test_graph,
        compile_test_graph,
        new_state_graph,
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
    from .polling import (
        is_terminal,
        ok_body,
        wait_for_run_status,
        wait_for_run_status_async,
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
    from .sse import SseFrame, SseReader, decode_frame, read_frame


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
    "LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON": (
        "vaultspec_a2a.testing.catalog",
        "LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON",
    ),
    "LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON": (
        "vaultspec_a2a.testing.catalog",
        "LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON",
    ),
    "LIVE_PROVIDER_PREREQUISITES": (
        "vaultspec_a2a.testing.catalog",
        "LIVE_PROVIDER_PREREQUISITES",
    ),
    "NoSelectableLaneError": ("vaultspec_a2a.testing.catalog", "NoSelectableLaneError"),
    "async_catalog_run_fields": (
        "vaultspec_a2a.testing.catalog",
        "async_catalog_run_fields",
    ),
    "async_fetch_in_process_selection": (
        "vaultspec_a2a.testing.catalog",
        "async_fetch_in_process_selection",
    ),
    "async_fetch_provider_catalog": (
        "vaultspec_a2a.testing.catalog",
        "async_fetch_provider_catalog",
    ),
    "catalog_run_fields": ("vaultspec_a2a.testing.catalog", "catalog_run_fields"),
    "declared_lane_model_value": (
        "vaultspec_a2a.testing.catalog",
        "declared_lane_model_value",
    ),
    "fetch_in_process_selection": (
        "vaultspec_a2a.testing.catalog",
        "fetch_in_process_selection",
    ),
    "fetch_in_process_selection_at": (
        "vaultspec_a2a.testing.catalog",
        "fetch_in_process_selection_at",
    ),
    "fetch_provider_catalog": (
        "vaultspec_a2a.testing.catalog",
        "fetch_provider_catalog",
    ),
    "in_process_lane_selection": (
        "vaultspec_a2a.testing.catalog",
        "in_process_lane_selection",
    ),
    "in_process_selection": ("vaultspec_a2a.testing.catalog", "in_process_selection"),
    "live_provider_catalog_selector_is_configured": (
        "vaultspec_a2a.testing.catalog",
        "live_provider_catalog_selector_is_configured",
    ),
    "live_provider_override_selector_is_configured": (
        "vaultspec_a2a.testing.catalog",
        "live_provider_override_selector_is_configured",
    ),
    "named_lane_selection": ("vaultspec_a2a.testing.catalog", "named_lane_selection"),
    "override_selection_from_served_catalog": (
        "vaultspec_a2a.testing.catalog",
        "override_selection_from_served_catalog",
    ),
    "selection_from_served_catalog": (
        "vaultspec_a2a.testing.catalog",
        "selection_from_served_catalog",
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
    "add_test_node": ("vaultspec_a2a.testing.graph", "add_test_node"),
    "ainvoke_test_graph": ("vaultspec_a2a.testing.graph", "ainvoke_test_graph"),
    "compile_test_graph": ("vaultspec_a2a.testing.graph", "compile_test_graph"),
    "new_state_graph": ("vaultspec_a2a.testing.graph", "new_state_graph"),
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
    "is_terminal": ("vaultspec_a2a.testing.polling", "is_terminal"),
    "ok_body": ("vaultspec_a2a.testing.polling", "ok_body"),
    "wait_for_run_status": ("vaultspec_a2a.testing.polling", "wait_for_run_status"),
    "wait_for_run_status_async": (
        "vaultspec_a2a.testing.polling",
        "wait_for_run_status_async",
    ),
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
    "SseFrame": ("vaultspec_a2a.testing.sse", "SseFrame"),
    "SseReader": ("vaultspec_a2a.testing.sse", "SseReader"),
    "decode_frame": ("vaultspec_a2a.testing.sse", "decode_frame"),
    "read_frame": ("vaultspec_a2a.testing.sse", "read_frame"),
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
    "LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON",
    "LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON",
    "LIVE_PROVIDER_PREREQUISITES",
    "MARKER_NAME",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "SCRATCH_ROLE",
    "SERVICE_MARKER",
    "SESSION_LEASE_KEY",
    "Lease",
    "LeaseAcquisitionTimeoutError",
    "LivenessWatch",
    "NoSelectableLaneError",
    "PortAllocationError",
    "ProgressDeadline",
    "ProgressStalledError",
    "ResolvedService",
    "ResourceClaim",
    "ResourceDeclarationError",
    "ResourceDiedError",
    "ResourceSpec",
    "SseFrame",
    "SseReader",
    "add_test_node",
    "ainvoke_test_graph",
    "allocate_free_ports",
    "apply_layer_markers",
    "armed_desktop_app_home",
    "armed_environment",
    "async_catalog_run_fields",
    "async_fetch_in_process_selection",
    "async_fetch_provider_catalog",
    "await_child",
    "catalog_run_fields",
    "child_tree_progress",
    "compile_test_graph",
    "declared_claims",
    "declared_lane_model_value",
    "decode_frame",
    "effective_worker_count",
    "exclusive_keys",
    "fetch_in_process_selection",
    "fetch_in_process_selection_at",
    "fetch_provider_catalog",
    "file_size_fingerprint",
    "forfeits_purity",
    "free_port",
    "hold_for_process_lifetime",
    "hold_lease",
    "in_process_lane_selection",
    "in_process_selection",
    "is_terminal",
    "lease_home",
    "live_peer_sessions",
    "live_provider_catalog_selector_is_configured",
    "live_provider_override_selector_is_configured",
    "machine_cpu_budget",
    "measured_child_startup_s",
    "named_lane_selection",
    "new_state_graph",
    "ok_body",
    "override_selection_from_served_catalog",
    "plant_link_to_file",
    "read_acp_frame",
    "read_frame",
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
    "selection_from_served_catalog",
    "session_scratch_dir",
    "settings_override",
    "simulator_command",
    "uses_impure_fixture",
    "wait_for",
    "wait_for_run_status",
    "wait_for_run_status_async",
]
