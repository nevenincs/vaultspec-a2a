"""Current schema identity for recoverable control-action deadlines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..thread.enums import (
    RECOVERY_ACTION_TYPES,
    ControlActionResultStatus,
    ControlActionType,
)
from .write_authority_schema import normalize_schema_expression

if TYPE_CHECKING:
    from collections.abc import Mapping

RECOVERY_ACTION_SQL_VALUES = ", ".join(
    repr(action.value) for action in RECOVERY_ACTION_TYPES
)
CONTROL_ACTION_SQL_VALUES = ", ".join(
    repr(action.value) for action in ControlActionType
)

#: The only action a continuation queue holds, and the status that says it is
#: still waiting. Spelled once so the column invariants, the partial index and
#: the queue queries cannot drift apart on what "queued" selects.
CONTINUATION_ACTION_SQL_VALUE = repr(ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value)
QUEUED_RESULT_SQL_VALUE = repr(ControlActionResultStatus.QUEUED.value)

QUEUED_ROW_PREDICATE = f"result_status = {QUEUED_RESULT_SQL_VALUE}"
QUEUE_POSITION_BOUNDED_PREDICATE = (
    "queue_position IS NULL OR (queue_position >= 1 "
    f"AND action_type = {CONTINUATION_ACTION_SQL_VALUE})"
)
# A queued reservation owns no write authority: it carries a position, it has
# bound no graph receipt, and it cannot already be applied.
QUEUED_RESERVATION_PREDICATE = (
    f"result_status <> {QUEUED_RESULT_SQL_VALUE} OR (queue_position IS NOT NULL "
    "AND graph_receipt_json IS NULL AND applied_at IS NULL)"
)
RECOVERY_DEADLINE_CHECKS = {
    "ck_control_actions_action_type_current": (
        f"action_type IN ({CONTROL_ACTION_SQL_VALUES})"
    ),
    "ck_control_actions_recovery_deadline_required": (
        f"(action_type IN ({RECOVERY_ACTION_SQL_VALUES}) "
        "AND recovery_deadline_at IS NOT NULL) OR "
        f"(action_type NOT IN ({RECOVERY_ACTION_SQL_VALUES}) "
        "AND recovery_deadline_at IS NULL)"
    ),
}


def recovery_deadline_checks_match(checks: Mapping[str, str]) -> bool:
    """Return whether the exact current deadline discriminator is installed."""
    normalized = {
        name.lower(): normalize_schema_expression(predicate)
        for name, predicate in checks.items()
    }
    return all(
        normalized.get(name) == normalize_schema_expression(predicate)
        for name, predicate in RECOVERY_DEADLINE_CHECKS.items()
    )
