"""Core orchestration logic and state."""

import importlib

from .anchoring import build_anchoring_context as build_anchoring_context
from .config import Settings, settings
from .context import (
    compact_context as compact_context,
)
from .context import (
    estimate_tokens as estimate_tokens,
)
from .context import (
    prepare_handoff as prepare_handoff,
)
from .context import (
    should_compact as should_compact,
)
from .exceptions import (
    AgentConfigNotFoundError,
    AgentProcessError,
    ConfigError,
    ContextOverflowError,
    DatabaseError,
    ErrorSeverity,
    EventAggregatorError,
    GitWorkspaceError,
    MergeConflictError,
    NicknameConflictError,
    PermissionDeniedError,
    ProtocolError,
    RecoveryAction,
    TeamConfigNotFoundError,
    TokenBudgetExceededError,
    VaultspecError,
    WorkerExecutionError,
    WorkspaceError,
)
from .metadata import (
    ContextRef as ContextRef,
)
from .metadata import (
    ThreadMetadata as ThreadMetadata,
)
from .metadata import (
    discover_context_refs as discover_context_refs,
)
from .metadata import (
    generate_nickname as generate_nickname,
)
from .models import (
    ArtifactRef as ArtifactRef,
)
from .models import (
    PlanStep as PlanStep,
)
from .models import (
    TokenUsageEntry as TokenUsageEntry,
)
from .nodes.supervisor import create_supervisor_node as create_supervisor_node
from .nodes.worker import create_worker_node as create_worker_node
from .phase import infer_phase_from_vault_index as infer_phase_from_vault_index
from .preamble import (
    build_context_preamble as build_context_preamble,
)
from .state import TeamState
from .task_queue import create_mark_task_complete_tool as create_mark_task_complete_tool
from .team_config import (
    AgentCapabilitiesConfig as AgentCapabilitiesConfig,
)
from .team_config import (
    AgentConfig as AgentConfig,
)
from .team_config import (
    AgentModelConfig as AgentModelConfig,
)
from .team_config import (
    AgentPermissionsConfig as AgentPermissionsConfig,
)
from .team_config import (
    AgentPersonaConfig as AgentPersonaConfig,
)
from .team_config import (
    SupervisorConfig as SupervisorConfig,
)
from .team_config import (
    TeamConfig as TeamConfig,
)
from .team_config import (
    TeamDefaultsConfig as TeamDefaultsConfig,
)
from .team_config import (
    TeamGraphConfig as TeamGraphConfig,
)
from .team_config import (
    TeamPermissionsConfig as TeamPermissionsConfig,
)
from .team_config import (
    TeamPersonaConfig as TeamPersonaConfig,
)
from .team_config import (
    TopologyConfig as TopologyConfig,
)
from .team_config import (
    TopologyType as TopologyType,
)
from .team_config import (
    WorkerOverrideConfig as WorkerOverrideConfig,
)
from .team_config import (
    WorkerRef as WorkerRef,
)
from .team_config import (
    discover_team_preset_ids as discover_team_preset_ids,
)
from .team_config import (
    load_agent_config as load_agent_config,
)
from .team_config import (
    load_team_config as load_team_config,
)


# Lazy imports to break circular dependencies:
# - core.aggregator <-> api.websocket
# - core.graph -> providers.factory -> acp_chat_model -> team_config
# -> core.__init__
_LAZY_IMPORTS = {
    "EventAggregator": ".aggregator",
    "StreamableGraph": ".aggregator",
    "build_initial_vault_index": ".graph",
    "compile_team_graph": ".graph",
}


def __getattr__(name: str) -> object:
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
