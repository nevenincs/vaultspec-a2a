"""Bind the recovery deadline to a dispatchable row, not to an action type.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Spelled literally rather than imported: a revision describes the schema at
# one moment in the chain, and an import would re-describe it from whatever the
# package means later.
_RECOVERY_ACTIONS = (
    "'ingest', 'resume', 'cancel', 'permission_response_submitted', "
    "'message_followup_requested'"
)
_DISPATCHABLE_RESULTS = "'accepted_not_applied', 'queued'"
_DEADLINE_CONSTRAINT = "ck_control_actions_recovery_deadline_required"

# The invariant 0021 installed: a deadline belongs to every row of a recovery
# action type, whatever that row's outcome.
_ACTION_TYPE_DEADLINE = (
    f"(action_type IN ({_RECOVERY_ACTIONS}) "
    "AND recovery_deadline_at IS NOT NULL) OR "
    f"(action_type NOT IN ({_RECOVERY_ACTIONS}) "
    "AND recovery_deadline_at IS NULL)"
)
# The narrowed invariant: a deadline belongs to a row a dispatcher may still
# deliver. A settled row keeps the deadline it was accepted with, so the middle
# clause admits either, and a row written already settled carries none.
_DISPATCHABLE_DEADLINE = (
    f"(action_type IN ({_RECOVERY_ACTIONS}) "
    f"AND result_status IN ({_DISPATCHABLE_RESULTS}) "
    "AND recovery_deadline_at IS NOT NULL) OR "
    f"(action_type IN ({_RECOVERY_ACTIONS}) "
    f"AND result_status NOT IN ({_DISPATCHABLE_RESULTS})) OR "
    f"(action_type NOT IN ({_RECOVERY_ACTIONS}) "
    "AND recovery_deadline_at IS NULL)"
)


class SettledActionWithoutDeadlineError(RuntimeError):
    """A settled row carries no deadline, which the prior invariant required."""


def _refuse_deadlineless_settled_rows() -> None:
    """Stop the downgrade before any DDL when a stored row cannot satisfy 0021.

    The narrowed invariant lets a row written already settled carry no
    deadline, and this revision's own writers take that permission. 0021
    requires one of every recovery-type row, and no deadline can be invented
    for work nobody accepted, so such a store cannot step back.
    """
    deadlineless = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM control_actions "
                f"WHERE action_type IN ({_RECOVERY_ACTIONS}) "
                "AND recovery_deadline_at IS NULL LIMIT 1"
            )
        )
        .first()
    )
    if deadlineless:
        raise SettledActionWithoutDeadlineError(
            "a stored control action of a recovery type carries no recovery "
            "deadline. The invariant this revision steps back to requires one "
            "of every such row, and a deadline no acceptance stood behind "
            "cannot be inferred; keep this store at or above revision 0027."
        )


def upgrade() -> None:
    """Narrow the deadline CHECK to the rows a dispatcher may still deliver.

    No stored row is refused: every row valid under 0021 is valid here, because
    the new predicate only ADMITS cases the old one rejected. The CHECK change
    rebuilds the table, as SQLite needs.
    """
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.drop_constraint(_DEADLINE_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(_DEADLINE_CONSTRAINT, _DISPATCHABLE_DEADLINE)


def downgrade() -> None:
    """Restore the action-type-only invariant 0021 installed."""
    _refuse_deadlineless_settled_rows()
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.drop_constraint(_DEADLINE_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(_DEADLINE_CONSTRAINT, _ACTION_TYPE_DEADLINE)
