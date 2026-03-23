"""Core orchestration logic and state."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aggregator import EventAggregator as EventAggregator
    from .aggregator import StreamableGraph as StreamableGraph

from .config import Settings, settings

# Lazy imports: deferred to break circular dependencies and reduce cold-start.
_LAZY_IMPORTS: dict[str, str] = {}

# Compatibility redirects: as files move to new top-level packages during the
# core-layer decomposition, entries are added here so existing ``from ..core
# import X`` statements continue to resolve.  Format:
#   "SymbolName": ("new.absolute.module.path", "SymbolName")
# Populated incrementally during Phases 1-6; removed in Phase 7 cleanup.
_REDIRECTS: dict[str, tuple[str, str]] = {
    # Phase 1: thread/ — exceptions
    "AgentConfigNotFoundError": (
        "vaultspec_a2a.thread.errors",
        "AgentConfigNotFoundError",
    ),
    "AgentProcessError": ("vaultspec_a2a.thread.errors", "AgentProcessError"),
    "ConfigError": ("vaultspec_a2a.thread.errors", "ConfigError"),
    "ContextOverflowError": ("vaultspec_a2a.thread.errors", "ContextOverflowError"),
    "DatabaseError": ("vaultspec_a2a.thread.errors", "DatabaseError"),
    "ErrorSeverity": ("vaultspec_a2a.thread.errors", "ErrorSeverity"),
    "EventAggregatorError": ("vaultspec_a2a.thread.errors", "EventAggregatorError"),
    "GitWorkspaceError": ("vaultspec_a2a.thread.errors", "GitWorkspaceError"),
    "MergeConflictError": ("vaultspec_a2a.thread.errors", "MergeConflictError"),
    "NicknameConflictError": ("vaultspec_a2a.thread.errors", "NicknameConflictError"),
    "PermissionDeniedError": ("vaultspec_a2a.thread.errors", "PermissionDeniedError"),
    "ProtocolError": ("vaultspec_a2a.thread.errors", "ProtocolError"),
    "RecoveryAction": ("vaultspec_a2a.thread.errors", "RecoveryAction"),
    "TeamConfigNotFoundError": (
        "vaultspec_a2a.thread.errors",
        "TeamConfigNotFoundError",
    ),
    "TokenBudgetExceededError": (
        "vaultspec_a2a.thread.errors",
        "TokenBudgetExceededError",
    ),
    "VaultspecError": ("vaultspec_a2a.thread.errors", "VaultspecError"),
    "WorkerExecutionError": ("vaultspec_a2a.thread.errors", "WorkerExecutionError"),
    "WorkspaceError": ("vaultspec_a2a.thread.errors", "WorkspaceError"),
    # Phase 1: thread/ — state
    "TeamState": ("vaultspec_a2a.thread.state", "TeamState"),
    # Phase 1: thread/ — models
    "ArtifactRef": ("vaultspec_a2a.thread.models", "ArtifactRef"),
    "PlanStep": ("vaultspec_a2a.thread.models", "PlanStep"),
    "TokenUsageEntry": ("vaultspec_a2a.thread.models", "TokenUsageEntry"),
    # Phase 2: domain_config + control/config
    "DomainConfig": ("vaultspec_a2a.domain_config", "DomainConfig"),
    # Phase 3: context/ — metadata
    "ContextRef": ("vaultspec_a2a.context.metadata", "ContextRef"),
    "ThreadMetadata": ("vaultspec_a2a.context.metadata", "ThreadMetadata"),
    "discover_context_refs": (
        "vaultspec_a2a.context.metadata",
        "discover_context_refs",
    ),
    "generate_nickname": ("vaultspec_a2a.context.metadata", "generate_nickname"),
    # Phase 3: context/ — preamble
    "build_context_preamble": (
        "vaultspec_a2a.context.preamble",
        "build_context_preamble",
    ),
    # Phase 3: context/ — anchoring
    "build_anchoring_context": (
        "vaultspec_a2a.context.anchoring",
        "build_anchoring_context",
    ),
    # Phase 3: context/ — stage (was phase.py)
    "infer_phase_from_vault_index": (
        "vaultspec_a2a.context.stage",
        "infer_phase_from_vault_index",
    ),
    "PHASE_ORDER": ("vaultspec_a2a.context.stage", "PHASE_ORDER"),
    # Phase 3: context/ — token_budget (was context.py)
    "compact_context": ("vaultspec_a2a.context.token_budget", "compact_context"),
    "estimate_tokens": ("vaultspec_a2a.context.token_budget", "estimate_tokens"),
    "prepare_handoff": ("vaultspec_a2a.context.token_budget", "prepare_handoff"),
    "should_compact": ("vaultspec_a2a.context.token_budget", "should_compact"),
    # Phase 3: context/ — rules
    "RuleManager": ("vaultspec_a2a.context.rules", "RuleManager"),
    # Phase 4: team/ — team_config
    "AgentCapabilitiesConfig": (
        "vaultspec_a2a.team.team_config",
        "AgentCapabilitiesConfig",
    ),
    "AgentConfig": ("vaultspec_a2a.team.team_config", "AgentConfig"),
    "AgentModelConfig": ("vaultspec_a2a.team.team_config", "AgentModelConfig"),
    "AgentPermissionsConfig": (
        "vaultspec_a2a.team.team_config",
        "AgentPermissionsConfig",
    ),
    "AgentPersonaConfig": ("vaultspec_a2a.team.team_config", "AgentPersonaConfig"),
    "SupervisorConfig": ("vaultspec_a2a.team.team_config", "SupervisorConfig"),
    "TeamConfig": ("vaultspec_a2a.team.team_config", "TeamConfig"),
    "TeamDefaultsConfig": ("vaultspec_a2a.team.team_config", "TeamDefaultsConfig"),
    "TeamGraphConfig": ("vaultspec_a2a.team.team_config", "TeamGraphConfig"),
    "TeamPermissionsConfig": (
        "vaultspec_a2a.team.team_config",
        "TeamPermissionsConfig",
    ),
    "TeamPersonaConfig": ("vaultspec_a2a.team.team_config", "TeamPersonaConfig"),
    "TopologyConfig": ("vaultspec_a2a.team.team_config", "TopologyConfig"),
    "TopologyType": ("vaultspec_a2a.team.team_config", "TopologyType"),
    "WorkerOverrideConfig": ("vaultspec_a2a.team.team_config", "WorkerOverrideConfig"),
    "WorkerRef": ("vaultspec_a2a.team.team_config", "WorkerRef"),
    "discover_team_preset_ids": (
        "vaultspec_a2a.team.team_config",
        "discover_team_preset_ids",
    ),
    "load_agent_config": ("vaultspec_a2a.team.team_config", "load_agent_config"),
    "load_team_config": ("vaultspec_a2a.team.team_config", "load_team_config"),
    # Phase 5: graph/ — compiler
    "build_initial_vault_index": (
        "vaultspec_a2a.graph.compiler",
        "build_initial_vault_index",
    ),
    "compile_team_graph": ("vaultspec_a2a.graph.compiler", "compile_team_graph"),
    # Phase 5: graph/ — nodes
    "create_supervisor_node": (
        "vaultspec_a2a.graph.nodes.supervisor",
        "create_supervisor_node",
    ),
    "create_worker_node": ("vaultspec_a2a.graph.nodes.worker", "create_worker_node"),
    # Phase 5: graph/ — tools
    "create_mark_task_complete_tool": (
        "vaultspec_a2a.graph.tools.task_queue",
        "create_mark_task_complete_tool",
    ),
    # Phase 6: streaming/ — aggregator
    "EventAggregator": (
        "vaultspec_a2a.streaming.aggregator",
        "EventAggregator",
    ),
    "StreamableGraph": (
        "vaultspec_a2a.streaming.aggregator",
        "StreamableGraph",
    ),
}


def __getattr__(name: str) -> object:
    if name in _REDIRECTS:
        module_path, attr = _REDIRECTS[name]
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "AgentCapabilitiesConfig",
    "AgentConfig",
    "AgentConfigNotFoundError",
    "AgentModelConfig",
    "AgentPermissionsConfig",
    "AgentPersonaConfig",
    "AgentProcessError",
    "ArtifactRef",
    "ConfigError",
    "ContextOverflowError",
    "ContextRef",
    "DatabaseError",
    "ErrorSeverity",
    "EventAggregator",
    "EventAggregatorError",
    "GitWorkspaceError",
    "MergeConflictError",
    "NicknameConflictError",
    "PermissionDeniedError",
    "PlanStep",
    "ProtocolError",
    "RecoveryAction",
    "Settings",
    "StreamableGraph",
    "SupervisorConfig",
    "TeamConfig",
    "TeamConfigNotFoundError",
    "TeamDefaultsConfig",
    "TeamGraphConfig",
    "TeamPermissionsConfig",
    "TeamPersonaConfig",
    "TeamState",
    "ThreadMetadata",
    "TokenBudgetExceededError",
    "TokenUsageEntry",
    "TopologyConfig",
    "TopologyType",
    "VaultspecError",
    "WorkerExecutionError",
    "WorkerOverrideConfig",
    "WorkerRef",
    "WorkspaceError",
    "build_anchoring_context",
    "build_context_preamble",
    "build_initial_vault_index",
    "compact_context",
    "compile_team_graph",
    "create_mark_task_complete_tool",
    "create_supervisor_node",
    "create_worker_node",
    "discover_context_refs",
    "discover_team_preset_ids",
    "estimate_tokens",
    "generate_nickname",
    "infer_phase_from_vault_index",
    "load_agent_config",
    "load_team_config",
    "prepare_handoff",
    "settings",
    "should_compact",
]
