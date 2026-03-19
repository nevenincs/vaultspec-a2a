"""Durable orchestration journal and repair metadata.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add durable repair metadata plus control and permission journals."""
    op.add_column(
        "threads",
        sa.Column(
            "repair_status",
            sa.String(),
            nullable=False,
            server_default="healthy",
        ),
    )
    op.add_column(
        "threads",
        sa.Column("repair_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "threads",
        sa.Column(
            "execution_readiness",
            sa.String(),
            nullable=False,
            server_default="healthy",
        ),
    )
    op.add_column(
        "threads",
        sa.Column("last_requested_action", sa.String(), nullable=True),
    )
    op.add_column(
        "threads",
        sa.Column("last_applied_action", sa.String(), nullable=True),
    )
    op.add_column(
        "threads",
        sa.Column(
            "repair_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "threads",
        sa.Column("recovery_epoch", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "permission_requests",
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("pause_reason_type", sa.String(), nullable=False),
        sa.Column("tool_call", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("allowed_options_json", sa.Text(), nullable=False),
        sa.Column("request_status", sa.String(), nullable=False),
        sa.Column("response_option_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "ix_permission_requests_thread_id",
        "permission_requests",
        ["thread_id"],
    )
    op.create_index(
        "ix_permission_requests_status",
        "permission_requests",
        ["request_status"],
    )

    op.create_table(
        "control_actions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("result_status", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "idempotency_key",
            name="uq_control_actions_thread_id_idempotency_key",
        ),
    )
    op.create_index("ix_control_actions_thread_id", "control_actions", ["thread_id"])
    op.create_index("ix_control_actions_request_id", "control_actions", ["request_id"])


def downgrade() -> None:
    """Drop orchestration journal tables and repair metadata."""
    op.drop_index("ix_control_actions_request_id", table_name="control_actions")
    op.drop_index("ix_control_actions_thread_id", table_name="control_actions")
    op.drop_table("control_actions")

    op.drop_index("ix_permission_requests_status", table_name="permission_requests")
    op.drop_index("ix_permission_requests_thread_id", table_name="permission_requests")
    op.drop_table("permission_requests")

    op.drop_column("threads", "recovery_epoch")
    op.drop_column("threads", "repair_generation")
    op.drop_column("threads", "last_applied_action")
    op.drop_column("threads", "last_requested_action")
    op.drop_column("threads", "execution_readiness")
    op.drop_column("threads", "repair_reason")
    op.drop_column("threads", "repair_status")
