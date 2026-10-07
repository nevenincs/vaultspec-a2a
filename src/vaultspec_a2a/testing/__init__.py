"""Resource-aware test execution.

The suite's contention machinery: a machine-readable resource vocabulary
(``resources``), machine-global leases arbitrating exclusive use across
processes and sessions (``leases``), progress-based deadlines that fail on
death or stall rather than on elapsed wall clock (``progress``), run-status
polling built on them (``polling``), registry-backed service endpoint
resolution (``endpoints``), and the pytest plugin
(``plugin``) that derives scheduling groups, timeout backstops, and lease
acquisition from the declarations. The ACP test peer (``acp``) is the simulated
agent side of the protocol over stdio, with the frame builders and the request and
reply exchange a client-side test uses against it. Beside them sits the
real-process support every test tier composes rather than retypes: the gateway
boot and its peers (``boot``), the loopback listeners a test points code at
(``http``), the run-start verb shaped once (``verbs``), and the in-process
fixture lanes a test gateway or test process holds (``lanes``).

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
        ACP_PROTOCOL_VERSION,
        ACP_SIMULATOR_PATH,
        REQUEST_PERMISSION_METHOD,
        acp_request,
        exchange_acp_request,
        initialize_request,
        initialize_result,
        read_acp_frame,
        request_permission_params,
        request_permission_request,
        simulator_command,
    )
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
        adopted_spawner,
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
        unvalidated_selection,
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
    from .cli import run_cli
    from .endpoints import ResolvedService, resolve_gateway_url, resolve_service
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
    from .http import (
        JsonReplyHandler,
        health_listener,
        loopback_uvicorn,
        serve_handler,
        serve_on_loopback,
        serve_on_loopback_in_thread,
        uvicorn_started,
    )
    from .lanes import (
        armed_lane_environment,
        deterministic_model_assignment,
        seated_lanes,
    )
    from .leases import (
        LEASE_TTL_MS,
        Lease,
        LeaseAcquisitionTimeoutError,
        hold_lease,
        lease_home,
    )
    from .links import plant_link_to_file
    from .markers import LayerRule, apply_layer_markers
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
    from .sse import SseFrame, SseReader, decode_frame, read_frame
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
    "ACP_PROTOCOL_VERSION": ("vaultspec_a2a.testing.acp", "ACP_PROTOCOL_VERSION"),
    "ACP_SIMULATOR_PATH": ("vaultspec_a2a.testing.acp", "ACP_SIMULATOR_PATH"),
    "REQUEST_PERMISSION_METHOD": (
        "vaultspec_a2a.testing.acp",
        "REQUEST_PERMISSION_METHOD",
    ),
    "acp_request": ("vaultspec_a2a.testing.acp", "acp_request"),
    "exchange_acp_request": ("vaultspec_a2a.testing.acp", "exchange_acp_request"),
    "initialize_request": ("vaultspec_a2a.testing.acp", "initialize_request"),
    "initialize_result": ("vaultspec_a2a.testing.acp", "initialize_result"),
    "read_acp_frame": ("vaultspec_a2a.testing.acp", "read_acp_frame"),
    "request_permission_params": (
        "vaultspec_a2a.testing.acp",
        "request_permission_params",
    ),
    "request_permission_request": (
        "vaultspec_a2a.testing.acp",
        "request_permission_request",
    ),
    "simulator_command": ("vaultspec_a2a.testing.acp", "simulator_command"),
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
    "adopted_spawner": ("vaultspec_a2a.testing.boot", "adopted_spawner"),
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
    "unvalidated_selection": (
        "vaultspec_a2a.testing.catalog",
        "unvalidated_selection",
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
    "run_cli": ("vaultspec_a2a.testing.cli", "run_cli"),
    "ResolvedService": ("vaultspec_a2a.testing.endpoints", "ResolvedService"),
    "resolve_gateway_url": (
        "vaultspec_a2a.testing.endpoints",
        "resolve_gateway_url",
    ),
    "resolve_service": ("vaultspec_a2a.testing.endpoints", "resolve_service"),
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
    "armed_lane_environment": (
        "vaultspec_a2a.testing.lanes",
        "armed_lane_environment",
    ),
    "deterministic_model_assignment": (
        "vaultspec_a2a.testing.lanes",
        "deterministic_model_assignment",
    ),
    "seated_lanes": ("vaultspec_a2a.testing.lanes", "seated_lanes"),
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
    "LayerRule": ("vaultspec_a2a.testing.markers", "LayerRule"),
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
    "ACP_PROTOCOL_VERSION",
    "ACP_SIMULATOR_PATH",
    "CPU_BUDGET_ENV",
    "DEFAULT_ATTACH_CREDENTIAL",
    "DEFAULT_IDLE_WINDOW_S",
    "DEFAULT_OWNERSHIP_CAPABILITY",
    "FIRST_DEMAND_TIMEOUT",
    "FOREIGN_WORKER_PROGRAM",
    "IMPURE_FIXTURES",
    "LEASE_TTL_MS",
    "LIVE_PROVIDER_CATALOG_SELECTION_ENVIRON",
    "LIVE_PROVIDER_OVERRIDE_SELECTION_ENVIRON",
    "LIVE_PROVIDER_PREREQUISITES",
    "LOOPBACK_TIMEOUT",
    "MARKER_NAME",
    "READINESS_TIMEOUT",
    "REQUEST_PERMISSION_METHOD",
    "RESOURCES",
    "SCRATCH_PREFIX",
    "SCRATCH_ROLE",
    "SERVICE_MARKER",
    "SESSION_LEASE_KEY",
    "BootedGateway",
    "GatewayBootError",
    "JsonReplyHandler",
    "LayerRule",
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
    "RunVerbs",
    "SignalledChild",
    "SseFrame",
    "SseReader",
    "WatchedProcess",
    "acp_request",
    "add_test_node",
    "adopted_spawner",
    "ainvoke_test_graph",
    "allocate_free_ports",
    "apply_layer_markers",
    "armed_desktop_app_home",
    "armed_environment",
    "armed_gateway_env",
    "armed_lane_environment",
    "async_catalog_run_fields",
    "async_fetch_in_process_selection",
    "async_fetch_provider_catalog",
    "await_child",
    "await_gateway_ready",
    "await_ready",
    "booted_gateway",
    "broker_gateway_env",
    "catalog_run_fields",
    "child_tree_progress",
    "clean_subprocess_environment",
    "compile_test_graph",
    "declared_claims",
    "declared_lane_model_value",
    "decode_frame",
    "desktop_workspace",
    "deterministic_model_assignment",
    "effective_worker_count",
    "exchange_acp_request",
    "exclusive_keys",
    "fetch_in_process_selection",
    "fetch_in_process_selection_at",
    "fetch_provider_catalog",
    "file_size_fingerprint",
    "foreign_worker",
    "forfeits_purity",
    "free_port",
    "gateway_process_env",
    "gateway_script",
    "health_listener",
    "hold_for_process_lifetime",
    "hold_lease",
    "in_process_lane_selection",
    "in_process_selection",
    "initialize_request",
    "initialize_result",
    "is_terminal",
    "lease_home",
    "live_peer_sessions",
    "live_provider_catalog_selector_is_configured",
    "live_provider_override_selector_is_configured",
    "log_tail",
    "loopback_callback_bridge",
    "loopback_uvicorn",
    "machine_cpu_budget",
    "measured_child_startup_s",
    "named_lane_selection",
    "new_state_graph",
    "ok_body",
    "override_selection_from_served_catalog",
    "plant_link_to_file",
    "prune_stale_dirs",
    "read_acp_frame",
    "read_frame",
    "reap_process",
    "reap_tree",
    "register_session",
    "registry_watch",
    "request_permission_params",
    "request_permission_request",
    "reserve_scratch_ports",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_spec",
    "run_child",
    "run_cli",
    "seat_app_home",
    "seated_lanes",
    "selection_from_served_catalog",
    "serve_handler",
    "serve_on_loopback",
    "serve_on_loopback_in_thread",
    "session_scratch_dir",
    "settings_override",
    "simulator_command",
    "spawn_gateway",
    "spawn_logged",
    "spawn_signalled",
    "spawn_until_ready",
    "status_and_json",
    "unvalidated_selection",
    "uses_impure_fixture",
    "uvicorn_started",
    "wait_for",
    "wait_for_run_status",
    "wait_for_run_status_async",
    "worker_lifecycle_gateway_script",
]
