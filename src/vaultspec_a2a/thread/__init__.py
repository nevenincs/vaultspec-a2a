"""Expose thread-domain state and projection helpers.

The package defines thread enums, errors, models, state, snapshots, actor
tokens, and projection helpers. Snapshots also use
:mod:`vaultspec_a2a.graph.enums`.

:mod:`vaultspec_a2a.context` reads thread state.
:mod:`vaultspec_a2a.control` coordinates thread operations.
:mod:`vaultspec_a2a.database` persists thread records and projections.

Graph enums are this package's cross-package runtime dependency. Control and
database modules consume the thread API but aren't imported by it.

Exports are lazy (same pattern as :mod:`vaultspec_a2a.graph`): ``state`` pulls
the langgraph stack and ``snapshots``/``clarification`` build pydantic models,
which together cost over a second at import. Nearly every consumer imports a
submodule directly (``thread.errors``, ``thread.state``), and an eager facade
made each of those imports pay for all the siblings it never touched. The
``TYPE_CHECKING`` block keeps the facade's public surface statically visible.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actor_tokens import ActorTokenBundle as ActorTokenBundle
    from .clarification import ClarificationAnswers as ClarificationAnswers
    from .clarification import ClarificationKind as ClarificationKind
    from .clarification import ClarificationQuestion as ClarificationQuestion
    from .clarification import ClarificationRequest as ClarificationRequest
    from .clarification import pending_clarification as pending_clarification
    from .clarification import (
        validate_clarification_answers as validate_clarification_answers,
    )
    from .constants import DEFAULT_SUPERVISOR_ID as DEFAULT_SUPERVISOR_ID
    from .enums import ApprovalStatus as ApprovalStatus
    from .enums import ControlActionResultStatus as ControlActionResultStatus
    from .enums import ControlActionType as ControlActionType
    from .enums import InvalidTransitionError as InvalidTransitionError
    from .enums import PermissionRequestStatus as PermissionRequestStatus
    from .enums import RepairStatus as RepairStatus
    from .enums import ThreadStatus as ThreadStatus
    from .errors import AgentConfigNotFoundError as AgentConfigNotFoundError
    from .errors import AgentProcessError as AgentProcessError
    from .errors import ConfigError as ConfigError
    from .errors import ContextOverflowError as ContextOverflowError
    from .errors import DatabaseError as DatabaseError
    from .errors import EventAggregatorError as EventAggregatorError
    from .errors import NicknameConflictError as NicknameConflictError
    from .errors import PermissionDeniedError as PermissionDeniedError
    from .errors import ProtocolError as ProtocolError
    from .errors import ProviderSessionError as ProviderSessionError
    from .errors import TeamConfigNotFoundError as TeamConfigNotFoundError
    from .errors import TokenBudgetExceededError as TokenBudgetExceededError
    from .errors import VaultspecError as VaultspecError
    from .errors import WorkerExecutionError as WorkerExecutionError
    from .models import ArtifactRef as ArtifactRef
    from .models import PlanEntry as PlanEntry
    from .models import PlanStep as PlanStep
    from .models import TokenUsageEntry as TokenUsageEntry
    from .snapshots import (
        LOCALLY_RESPONDABLE_PAUSE_CAUSES as LOCALLY_RESPONDABLE_PAUSE_CAUSES,
    )
    from .snapshots import (
        PLAN_APPROVAL_PAUSE_CAUSES as PLAN_APPROVAL_PAUSE_CAUSES,
    )
    from .snapshots import CheckpointProjection as CheckpointProjection
    from .snapshots import ExecutionStateProjection as ExecutionStateProjection
    from .snapshots import ProjectedInterrupt as ProjectedInterrupt
    from .snapshots import classify_message_role as classify_message_role
    from .snapshots import derive_message_id as derive_message_id
    from .snapshots import extract_message_timestamp as extract_message_timestamp
    from .snapshots import (
        finalize_snapshot_replay_status as finalize_snapshot_replay_status,
    )
    from .snapshots import normalize_artifacts as normalize_artifacts
    from .snapshots import normalize_plan_entries as normalize_plan_entries
    from .snapshots import project_checkpoint_tuple as project_checkpoint_tuple
    from .state import TeamState as TeamState

_LAZY_IMPORTS = {
    "ActorTokenBundle": ".actor_tokens",
    "ClarificationAnswers": ".clarification",
    "ClarificationKind": ".clarification",
    "ClarificationQuestion": ".clarification",
    "ClarificationRequest": ".clarification",
    "pending_clarification": ".clarification",
    "validate_clarification_answers": ".clarification",
    "DEFAULT_SUPERVISOR_ID": ".constants",
    "ApprovalStatus": ".enums",
    "ControlActionResultStatus": ".enums",
    "ControlActionType": ".enums",
    "InvalidTransitionError": ".enums",
    "PermissionRequestStatus": ".enums",
    "RepairStatus": ".enums",
    "ThreadStatus": ".enums",
    "AgentConfigNotFoundError": ".errors",
    "AgentProcessError": ".errors",
    "ConfigError": ".errors",
    "ContextOverflowError": ".errors",
    "DatabaseError": ".errors",
    "EventAggregatorError": ".errors",
    "NicknameConflictError": ".errors",
    "PermissionDeniedError": ".errors",
    "ProtocolError": ".errors",
    "ProviderSessionError": ".errors",
    "TeamConfigNotFoundError": ".errors",
    "TokenBudgetExceededError": ".errors",
    "VaultspecError": ".errors",
    "WorkerExecutionError": ".errors",
    "ArtifactRef": ".models",
    "PlanEntry": ".models",
    "PlanStep": ".models",
    "TokenUsageEntry": ".models",
    "LOCALLY_RESPONDABLE_PAUSE_CAUSES": ".snapshots",
    "PLAN_APPROVAL_PAUSE_CAUSES": ".snapshots",
    "CheckpointProjection": ".snapshots",
    "ExecutionStateProjection": ".snapshots",
    "ProjectedInterrupt": ".snapshots",
    "classify_message_role": ".snapshots",
    "derive_message_id": ".snapshots",
    "extract_message_timestamp": ".snapshots",
    "finalize_snapshot_replay_status": ".snapshots",
    "normalize_artifacts": ".snapshots",
    "normalize_plan_entries": ".snapshots",
    "project_checkpoint_tuple": ".snapshots",
    "TeamState": ".state",
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
    "DEFAULT_SUPERVISOR_ID",
    "LOCALLY_RESPONDABLE_PAUSE_CAUSES",
    "PLAN_APPROVAL_PAUSE_CAUSES",
    "ActorTokenBundle",
    "AgentConfigNotFoundError",
    "AgentProcessError",
    "ApprovalStatus",
    "ArtifactRef",
    "CheckpointProjection",
    "ClarificationAnswers",
    "ClarificationKind",
    "ClarificationQuestion",
    "ClarificationRequest",
    "ConfigError",
    "ContextOverflowError",
    "ControlActionResultStatus",
    "ControlActionType",
    "DatabaseError",
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
    "pending_clarification",
    "project_checkpoint_tuple",
    "validate_clarification_answers",
]
