"""Bind recoverable action types to an explicit deadline.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_RECOVERY_ACTIONS = (
    "'ingest', 'resume', 'cancel', 'permission_response_submitted', "
    "'message_followup_requested'"
)
_ALL_ACTIONS = (
    "'ingest', 'resume', 'cancel', 'permission_request_created', "
    "'permission_response_submitted', 'permission_response_applied', "
    "'message_followup_requested', 'message_followup_applied', "
    "'repair_started', 'repair_finished'"
)
_ACTION_TYPE_CONSTRAINT = "ck_control_actions_action_type_current"
_DEADLINE_CONSTRAINT = "ck_control_actions_recovery_deadline_required"


class RecoveryDeadlineInvariantIncompatibleError(RuntimeError):
    """A populated store cannot prove the deadline of accepted work."""


def _require_empty_store() -> None:
    populated = op.get_bind().execute(
        sa.text(
            "SELECT 1 FROM threads UNION ALL "
            "SELECT 1 FROM control_actions LIMIT 1"
        )
    ).first()
    if populated:
        raise RecoveryDeadlineInvariantIncompatibleError(
            "control-action deadline authority requires a fresh current "
            "application home; existing action deadlines cannot be inferred"
        )


def upgrade() -> None:
    _require_empty_store()
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.create_check_constraint(
            _ACTION_TYPE_CONSTRAINT,
            f"action_type IN ({_ALL_ACTIONS})",
        )
        batch_op.create_check_constraint(
            _DEADLINE_CONSTRAINT,
            f"(action_type IN ({_RECOVERY_ACTIONS}) "
            "AND recovery_deadline_at IS NOT NULL) OR "
            f"(action_type NOT IN ({_RECOVERY_ACTIONS}) "
            "AND recovery_deadline_at IS NULL)",
        )


def downgrade() -> None:
    _require_empty_store()
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.drop_constraint(_DEADLINE_CONSTRAINT, type_="check")
        batch_op.drop_constraint(_ACTION_TYPE_CONSTRAINT, type_="check")
