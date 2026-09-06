"""Persist exact leased recovery attempts.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_CONDITIONS = (
    "'circuit_open', 'dispatch_pending', 'at_capacity', 'unreachable', 'rejected', "
    "'incompatible_state', 'no_active_project', 'credentials_required', "
    "'deadline_exceeded', 'not_found', 'terminal', 'input_required', 'conflict'"
)
_ACTION_TYPES = (
    "'ingest', 'resume', 'cancel', 'permission_request_created', "
    "'permission_response_submitted', 'permission_response_applied', "
    "'message_followup_requested', 'message_followup_applied', "
    "'repair_started', 'repair_finished'"
)


class RecoveryAttemptSchemaIncompatibleError(RuntimeError):
    """A populated store cannot acquire missing retry history retroactively."""


def _require_empty_store() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM threads LIMIT 1")).first():
        raise RecoveryAttemptSchemaIncompatibleError(
            "recovery attempt authority requires a fresh current application home; "
            "existing retry history and deadlines cannot be invented"
        )


def upgrade() -> None:
    _require_empty_store()
    op.create_table(
        "recovery_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("run_revision", sa.Integer(), nullable=False),
        sa.Column("writer_generation", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("action_receipt_id", sa.String(length=64), nullable=False),
        sa.Column("condition", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_eligible_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("claim_token", sa.String(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "run_revision >= 0",
            name="ck_recovery_attempts_run_revision_nonnegative",
        ),
        sa.CheckConstraint(
            "writer_generation >= 1",
            name="ck_recovery_attempts_writer_generation_positive",
        ),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name="ck_recovery_attempts_attempt_count_positive",
        ),
        sa.CheckConstraint(
            "next_eligible_at >= created_at AND deadline_at > created_at "
            "AND next_eligible_at <= deadline_at",
            name="ck_recovery_attempts_schedule_ordered",
        ),
        sa.CheckConstraint(
            "(claim_token IS NULL AND claim_expires_at IS NULL) OR "
            "(claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="ck_recovery_attempts_claim_complete",
        ),
        sa.CheckConstraint(
            "settled_at IS NULL OR claim_token IS NULL",
            name="ck_recovery_attempts_settled_unclaimed",
        ),
        sa.CheckConstraint(
            f"condition IN ({_CONDITIONS})",
            name="ck_recovery_attempts_condition_current",
        ),
        sa.CheckConstraint(
            f"action_type IN ({_ACTION_TYPES})",
            name="ck_recovery_attempts_action_type_current",
        ),
        sa.CheckConstraint(
            "length(trim(action_receipt_id)) >= 1 AND length(action_receipt_id) <= 64",
            name="ck_recovery_attempts_action_receipt_id_bounded",
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "run_revision",
            "writer_generation",
            "action_receipt_id",
            name="uq_recovery_attempts_writer",
        ),
    )
    op.create_index(
        "ix_recovery_attempts_due",
        "recovery_attempts",
        ["settled_at", "next_eligible_at", "claim_expires_at"],
    )
    op.create_index(
        "ix_recovery_attempts_thread_id",
        "recovery_attempts",
        ["thread_id"],
    )


def downgrade() -> None:
    _require_empty_store()
    op.drop_index("ix_recovery_attempts_thread_id", table_name="recovery_attempts")
    op.drop_index("ix_recovery_attempts_due", table_name="recovery_attempts")
    op.drop_table("recovery_attempts")
