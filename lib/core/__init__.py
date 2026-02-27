"""Core orchestration logic, state, and permissions."""

import importlib

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
    MergeConflictError,
    PermissionDeniedError,
    ProtocolError,
    RecoveryAction,
    TeamConfigNotFoundError,
    TokenBudgetExceededError,
    VaultspecError,
    WorkspaceError,
)
from .models import (
    ArtifactRef as ArtifactRef,
)
from .models import (
    PlanEntry as PlanEntry,
)
from .models import (
    TokenUsageEntry as TokenUsageEntry,
)
from .permissions import PermissionAction as PermissionAction
from .permissions import PermissionDecision as PermissionDecision
from .permissions import PermissionEngine
from .permissions import PermissionPolicy as PermissionPolicy
from .permissions import PermissionRequest as PermissionRequest
from .permissions import PermissionScope as PermissionScope
from .state import TeamState
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
    TopologyConfig as TopologyConfig,
)
from .team_config import (
    WorkerOverrideConfig as WorkerOverrideConfig,
)
from .team_config import (
    WorkerRef as WorkerRef,
)
from .team_config import (
    load_agent_config as load_agent_config,
)
from .team_config import (
    load_team_config as load_team_config,
)


# Lazy imports to break circular dependency (core.aggregator <-> api.websocket)
_LAZY_IMPORTS = {
    "EventAggregator": ".aggregator",
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
    "DatabaseError",
    "ErrorSeverity",
    "EventAggregator",
    "EventAggregatorError",
    "MergeConflictError",
    "PermissionAction",
    "PermissionDecision",
    "PermissionDeniedError",
    "PermissionEngine",
    "PermissionPolicy",
    "PermissionRequest",
    "PermissionScope",
    "PlanEntry",
    "ProtocolError",
    "RecoveryAction",
    "Settings",
    "SupervisorConfig",
    "TeamConfig",
    "TeamConfigNotFoundError",
    "TeamDefaultsConfig",
    "TeamState",
    "TokenBudgetExceededError",
    "TokenUsageEntry",
    "TopologyConfig",
    "VaultspecError",
    "WorkerOverrideConfig",
    "WorkerRef",
    "WorkspaceError",
    "compact_context",
    "estimate_tokens",
    "load_agent_config",
    "load_team_config",
    "prepare_handoff",
    "settings",
    "should_compact",
]
