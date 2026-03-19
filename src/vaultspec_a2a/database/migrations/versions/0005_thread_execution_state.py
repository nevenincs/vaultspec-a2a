"""Add durable latest execution-state projection.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add latest-row execution-state projection table."""
    op.create_table(
        "thread_execution_state",
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("checkpoint_id", sa.String(), nullable=True),
        sa.Column("parent_checkpoint_id", sa.String(), nullable=True),
        sa.Column("snapshot_created_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("recovery_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interrupt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_nodes_json", sa.Text(), nullable=False),
        sa.Column("interrupt_types_json", sa.Text(), nullable=False),
        sa.Column("tasks_json", sa.Text(), nullable=False),
        sa.Column("degraded_reasons_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_index(
        "ix_thread_execution_state_checkpoint_id",
        "thread_execution_state",
        ["checkpoint_id"],
    )


def downgrade() -> None:
    """Remove latest-row execution-state projection table."""
    op.drop_index(
        "ix_thread_execution_state_checkpoint_id",
        table_name="thread_execution_state",
    )
    op.drop_table("thread_execution_state")
