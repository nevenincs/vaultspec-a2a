"""Add durable thread-level plan approval state.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-09
"""

import sqlalchemy as sa

from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add thread-level durable approval-state columns."""
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("approval_status", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("approval_request_id", sa.String(), nullable=True)
        )
        batch_op.add_column(sa.Column("approval_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("approval_response_action_id", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("approval_updated_at", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    """Remove thread-level durable approval-state columns."""
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_column("approval_updated_at")
        batch_op.drop_column("approval_response_action_id")
        batch_op.drop_column("approval_reason")
        batch_op.drop_column("approval_request_id")
        batch_op.drop_column("approval_status")
