"""Current schema identity for recoverable control-action deadlines."""

from __future__ import annotations

from ..thread.enums import (
    RECOVERY_ACTION_TYPES,
    ControlActionResultStatus,
    ControlActionType,
)
from .write_authority_schema import CONTROL_ACTION_SQL_VALUES

__all__ = [
    "DISPATCHABLE_RESULT_STATUSES",
    "QUEUED_RESERVATION_PREDICATE",
    "QUEUED_ROW_PREDICATE",
    "QUEUE_POSITION_BOUNDED_PREDICATE",
    "RECOVERY_ACTION_SQL_VALUES",
    "RECOVERY_DEADLINE_CHECKS",
]

RECOVERY_ACTION_SQL_VALUES = ", ".join(
    repr(action.value) for action in RECOVERY_ACTION_TYPES
)

DISPATCHABLE_RESULT_STATUSES: tuple[ControlActionResultStatus, ...] = (
    ControlActionResultStatus.ACCEPTED_NOT_APPLIED,
    ControlActionResultStatus.QUEUED,
)
"""The outcomes of a journal row a dispatcher may still deliver.

A row is dispatchable when it is of a recovery action type AND still carries one
of these: accepted work awaiting delivery, or a reservation awaiting its
promotion. Every other outcome is settled - refused, duplicated, superseded,
cancelled or applied - and nothing will ever dispatch it.

Spelled once because three readers must agree on it: the deadline invariant that
requires a deadline, the recovery selection that reads one, and the writer guard
that refuses to invent one.
"""

_DISPATCHABLE_RESULT_SQL_VALUES = ", ".join(
    repr(status.value) for status in DISPATCHABLE_RESULT_STATUSES
)

#: The only action a continuation queue holds, and the status that says it is
#: still waiting. Spelled once so the column invariants, the partial index and
#: the queue queries cannot drift apart on what "queued" selects.
_CONTINUATION_ACTION_SQL_VALUE = repr(
    ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
)
_QUEUED_RESULT_SQL_VALUE = repr(ControlActionResultStatus.QUEUED.value)

QUEUED_ROW_PREDICATE = f"result_status = {_QUEUED_RESULT_SQL_VALUE}"
QUEUE_POSITION_BOUNDED_PREDICATE = (
    "queue_position IS NULL OR (queue_position >= 1 "
    f"AND action_type = {_CONTINUATION_ACTION_SQL_VALUE})"
)
# A queued reservation owns no write authority: it carries a position, it has
# bound no graph receipt, and it cannot already be applied.
QUEUED_RESERVATION_PREDICATE = (
    f"result_status <> {_QUEUED_RESULT_SQL_VALUE} OR (queue_position IS NOT NULL "
    "AND graph_receipt_json IS NULL AND applied_at IS NULL)"
)
#: The deadline invariant, which binds a deadline to a row that can still be
#: dispatched rather than to its action type alone. A dispatchable row carries
#: one; a row of a non-recovery type carries none; a settled row keeps whatever
#: it was accepted with, because a deadline is a fact about an acceptance and
#: settling does not revise it. Keying this on the action type alone obliged
#: every refusal and duplicate - rows nothing will ever dispatch - to invent a
#: deadline, and an invented deadline is the one thing a recovery coordinator
#: must never read.
RECOVERY_DEADLINE_CHECKS = {
    "ck_control_actions_action_type_current": (
        f"action_type IN ({CONTROL_ACTION_SQL_VALUES})"
    ),
    "ck_control_actions_recovery_deadline_required": (
        f"(action_type IN ({RECOVERY_ACTION_SQL_VALUES}) "
        f"AND result_status IN ({_DISPATCHABLE_RESULT_SQL_VALUES}) "
        "AND recovery_deadline_at IS NOT NULL) OR "
        f"(action_type IN ({RECOVERY_ACTION_SQL_VALUES}) "
        f"AND result_status NOT IN ({_DISPATCHABLE_RESULT_SQL_VALUES})) OR "
        f"(action_type NOT IN ({RECOVERY_ACTION_SQL_VALUES}) "
        "AND recovery_deadline_at IS NULL)"
    ),
}
