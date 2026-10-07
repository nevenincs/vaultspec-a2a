"""Expose thread-domain state and projection helpers.

The package defines thread enums, errors, models, state, snapshots, actor
tokens, run write authority, resume-value contracts, and projection helpers.
Snapshots also use :mod:`vaultspec_a2a.graph.enums`.

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
    from .action_receipts import canonical_json as canonical_json
    from .action_receipts import sha256_hex as sha256_hex
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
    from .enums import InterruptType as InterruptType
    from .enums import InvalidTransitionError as InvalidTransitionError
    from .enums import PermissionRequestStatus as PermissionRequestStatus
    from .enums import RepairStatus as RepairStatus
    from .enums import ThreadStatus as ThreadStatus
    from .errors import AgentConfigNotFoundError as AgentConfigNotFoundError
    from .errors import AgentProcessError as AgentProcessError
    from .errors import ConfigError as ConfigError
    from .errors import ContextOverflowError as ContextOverflowError
    from .errors import DatabaseError as DatabaseError
    from .errors import DocumentConformanceError as DocumentConformanceError
    from .errors import EventAggregatorError as EventAggregatorError
    from .errors import NicknameConflictError as NicknameConflictError
    from .errors import PermissionDeniedError as PermissionDeniedError
    from .errors import ProtocolError as ProtocolError
    from .errors import ProviderSessionError as ProviderSessionError
    from .errors import SupervisorRoutingError as SupervisorRoutingError
    from .errors import TeamConfigNotFoundError as TeamConfigNotFoundError
    from .errors import TokenBudgetExceededError as TokenBudgetExceededError
    from .errors import VaultspecError as VaultspecError
    from .errors import WorkerExecutionError as WorkerExecutionError
    from .models import ArtifactRef as ArtifactRef
    from .models import PlanEntry as PlanEntry
    from .models import PlanStep as PlanStep
    from .models import TokenUsageEntry as TokenUsageEntry
    from .resume_values import ApprovalVerdict as ApprovalVerdict
    from .resume_values import PermissionAnswer as PermissionAnswer
    from .resume_values import parse_approval_verdict as parse_approval_verdict
    from .resume_values import permission_resume_value as permission_resume_value
    from .snapshots import (
        LOCALLY_RESPONDABLE_PAUSE_CAUSES as LOCALLY_RESPONDABLE_PAUSE_CAUSES,
    )
    from .snapshots import (
        PLAN_APPROVAL_PAUSE_CAUSES as PLAN_APPROVAL_PAUSE_CAUSES,
    )
    from .snapshots import CheckpointProjection as CheckpointProjection
    from .snapshots import ExecutionStateProjection as ExecutionStateProjection
    from .snapshots import LiveInterrupt as LiveInterrupt
    from .snapshots import ProjectedInterrupt as ProjectedInterrupt
    from .snapshots import classify_message_role as classify_message_role
    from .snapshots import derive_message_id as derive_message_id
    from .snapshots import extract_message_timestamp as extract_message_timestamp
    from .snapshots import live_interrupts as live_interrupts
    from .snapshots import named_request_id as named_request_id
    from .snapshots import normalize_artifacts as normalize_artifacts
    from .snapshots import normalize_plan_entries as normalize_plan_entries
    from .snapshots import project_checkpoint_tuple as project_checkpoint_tuple
    from .snapshots import stamp_message_created_at as stamp_message_created_at
    from .snapshots import (
        unanswered_interrupt_values as unanswered_interrupt_values,
    )
    from .state import TeamState as TeamState
    from .write_authority import RECEIPT_ID_MAX_LENGTH as RECEIPT_ID_MAX_LENGTH
    from .write_authority import RunWriteAuthority as RunWriteAuthority
    from .write_authority import ThreadWriteExpectation as ThreadWriteExpectation

_LAZY_IMPORTS = {
    "canonical_json": ".action_receipts",
    "sha256_hex": ".action_receipts",
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
    "InterruptType": ".enums",
    "InvalidTransitionError": ".enums",
    "PermissionRequestStatus": ".enums",
    "RepairStatus": ".enums",
    "ThreadStatus": ".enums",
    "AgentConfigNotFoundError": ".errors",
    "AgentProcessError": ".errors",
    "ConfigError": ".errors",
    "ContextOverflowError": ".errors",
    "DatabaseError": ".errors",
    "DocumentConformanceError": ".errors",
    "EventAggregatorError": ".errors",
    "NicknameConflictError": ".errors",
    "PermissionDeniedError": ".errors",
    "ProtocolError": ".errors",
    "ProviderSessionError": ".errors",
    "SupervisorRoutingError": ".errors",
    "TeamConfigNotFoundError": ".errors",
    "TokenBudgetExceededError": ".errors",
    "VaultspecError": ".errors",
    "WorkerExecutionError": ".errors",
    "ArtifactRef": ".models",
    "PlanEntry": ".models",
    "PlanStep": ".models",
    "TokenUsageEntry": ".models",
    "ApprovalVerdict": ".resume_values",
    "PermissionAnswer": ".resume_values",
    "parse_approval_verdict": ".resume_values",
    "permission_resume_value": ".resume_values",
    "LOCALLY_RESPONDABLE_PAUSE_CAUSES": ".snapshots",
    "PLAN_APPROVAL_PAUSE_CAUSES": ".snapshots",
    "CheckpointProjection": ".snapshots",
    "ExecutionStateProjection": ".snapshots",
    "LiveInterrupt": ".snapshots",
    "ProjectedInterrupt": ".snapshots",
    "classify_message_role": ".snapshots",
    "derive_message_id": ".snapshots",
    "extract_message_timestamp": ".snapshots",
    "live_interrupts": ".snapshots",
    "named_request_id": ".snapshots",
    "normalize_artifacts": ".snapshots",
    "normalize_plan_entries": ".snapshots",
    "project_checkpoint_tuple": ".snapshots",
    "stamp_message_created_at": ".snapshots",
    "unanswered_interrupt_values": ".snapshots",
    "TeamState": ".state",
    "RECEIPT_ID_MAX_LENGTH": ".write_authority",
    "RunWriteAuthority": ".write_authority",
    "ThreadWriteExpectation": ".write_authority",
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
    "RECEIPT_ID_MAX_LENGTH",
    "ActorTokenBundle",
    "AgentConfigNotFoundError",
    "AgentProcessError",
    "ApprovalStatus",
    "ApprovalVerdict",
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
    "DocumentConformanceError",
    "EventAggregatorError",
    "ExecutionStateProjection",
    "InterruptType",
    "InvalidTransitionError",
    "LiveInterrupt",
    "NicknameConflictError",
    "PermissionAnswer",
    "PermissionDeniedError",
    "PermissionRequestStatus",
    "PlanEntry",
    "PlanStep",
    "ProjectedInterrupt",
    "ProtocolError",
    "ProviderSessionError",
    "RepairStatus",
    "RunWriteAuthority",
    "SupervisorRoutingError",
    "TeamConfigNotFoundError",
    "TeamState",
    "ThreadStatus",
    "ThreadWriteExpectation",
    "TokenBudgetExceededError",
    "TokenUsageEntry",
    "VaultspecError",
    "WorkerExecutionError",
    "canonical_json",
    "classify_message_role",
    "derive_message_id",
    "extract_message_timestamp",
    "live_interrupts",
    "named_request_id",
    "normalize_artifacts",
    "normalize_plan_entries",
    "parse_approval_verdict",
    "pending_clarification",
    "permission_resume_value",
    "project_checkpoint_tuple",
    "sha256_hex",
    "stamp_message_created_at",
    "unanswered_interrupt_values",
    "validate_clarification_answers",
]
