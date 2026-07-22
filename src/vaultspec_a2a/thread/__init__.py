"""Expose thread-domain state and projection helpers.

The package defines thread enums, errors, models, state, snapshots, actor
tokens, and projection helpers. Snapshots also use
:mod:`vaultspec_a2a.graph.enums`.

:mod:`vaultspec_a2a.context` reads thread state.
:mod:`vaultspec_a2a.control` coordinates thread operations.
:mod:`vaultspec_a2a.database` persists thread records and projections.

Graph enums are this package's cross-package runtime dependency. Control and
database modules consume the thread API but aren't imported by it.
"""

from .actor_tokens import (
    ActorTokenBundle as ActorTokenBundle,
)
from .constants import (
    DEFAULT_SUPERVISOR_ID as DEFAULT_SUPERVISOR_ID,
)
from .enums import (
    ApprovalStatus as ApprovalStatus,
)
from .enums import (
    ControlActionResultStatus as ControlActionResultStatus,
)
from .enums import (
    ControlActionType as ControlActionType,
)
from .enums import (
    InvalidTransitionError as InvalidTransitionError,
)
from .enums import (
    PermissionRequestStatus as PermissionRequestStatus,
)
from .enums import (
    RepairStatus as RepairStatus,
)
from .enums import (
    ThreadStatus as ThreadStatus,
)
from .errors import (
    AgentConfigNotFoundError as AgentConfigNotFoundError,
)
from .errors import (
    AgentProcessError as AgentProcessError,
)
from .errors import (
    ConfigError as ConfigError,
)
from .errors import (
    ContextOverflowError as ContextOverflowError,
)
from .errors import (
    DatabaseError as DatabaseError,
)
from .errors import (
    ErrorSeverity as ErrorSeverity,
)
from .errors import (
    EventAggregatorError as EventAggregatorError,
)
from .errors import (
    NicknameConflictError as NicknameConflictError,
)
from .errors import (
    PermissionDeniedError as PermissionDeniedError,
)
from .errors import (
    ProtocolError as ProtocolError,
)
from .errors import (
    ProviderSessionError as ProviderSessionError,
)
from .errors import (
    RecoveryAction as RecoveryAction,
)
from .errors import (
    TeamConfigNotFoundError as TeamConfigNotFoundError,
)
from .errors import (
    TokenBudgetExceededError as TokenBudgetExceededError,
)
from .errors import (
    VaultspecError as VaultspecError,
)
from .errors import (
    WorkerExecutionError as WorkerExecutionError,
)
from .models import (
    ArtifactRef as ArtifactRef,
)
from .models import (
    PlanEntry as PlanEntry,
)
from .models import (
    PlanStep as PlanStep,
)
from .models import (
    TokenUsageEntry as TokenUsageEntry,
)
from .snapshots import (
    PLAN_APPROVAL_PAUSE_CAUSES as PLAN_APPROVAL_PAUSE_CAUSES,
)
from .snapshots import (
    CheckpointProjection as CheckpointProjection,
)
from .snapshots import (
    ExecutionStateProjection as ExecutionStateProjection,
)
from .snapshots import (
    ProjectedInterrupt as ProjectedInterrupt,
)
from .snapshots import (
    classify_message_role as classify_message_role,
)
from .snapshots import (
    derive_message_id as derive_message_id,
)
from .snapshots import (
    extract_message_timestamp as extract_message_timestamp,
)
from .snapshots import (
    finalize_snapshot_replay_status as finalize_snapshot_replay_status,
)
from .snapshots import (
    normalize_artifacts as normalize_artifacts,
)
from .snapshots import (
    normalize_plan_entries as normalize_plan_entries,
)
from .snapshots import (
    project_checkpoint_tuple as project_checkpoint_tuple,
)
from .state import TeamState as TeamState

__all__ = [
    "DEFAULT_SUPERVISOR_ID",
    "PLAN_APPROVAL_PAUSE_CAUSES",
    "ActorTokenBundle",
    "AgentConfigNotFoundError",
    "AgentProcessError",
    "ApprovalStatus",
    "ArtifactRef",
    "CheckpointProjection",
    "ConfigError",
    "ContextOverflowError",
    "ControlActionResultStatus",
    "ControlActionType",
    "DatabaseError",
    "ErrorSeverity",
    "EventAggregatorError",
    "ExecutionStateProjection",
    "InvalidTransitionError",
    "NicknameConflictError",
    "PermissionDeniedError",
    "PermissionRequestStatus",
    "PlanEntry",
    "PlanStep",
    "ProjectedInterrupt",
    "ProtocolError",
    "ProviderSessionError",
    "RecoveryAction",
    "RepairStatus",
    "TeamConfigNotFoundError",
    "TeamState",
    "ThreadStatus",
    "TokenBudgetExceededError",
    "TokenUsageEntry",
    "VaultspecError",
    "WorkerExecutionError",
    "classify_message_role",
    "derive_message_id",
    "extract_message_timestamp",
    "finalize_snapshot_replay_status",
    "normalize_artifacts",
    "normalize_plan_entries",
    "project_checkpoint_tuple",
]
