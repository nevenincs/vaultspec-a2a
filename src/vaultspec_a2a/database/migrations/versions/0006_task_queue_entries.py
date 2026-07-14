"""Add worker task-queue entries table (ADR R5).

Relocates the worker task queue out of the ``.vault/plan`` markdown table
into A2A's own database alongside threads and checkpoints.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the thread-owned task-queue entries table."""
    op.create_table(
        "task_queue_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("feature_tag", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("plan_changeset_id", sa.String(), nullable=True),
        sa.Column("plan_step_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "position",
            name="uq_task_queue_entries_thread_id_position",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "task_key",
            name="uq_task_queue_entries_thread_id_task_key",
        ),
    )
    op.create_index(
        "ix_task_queue_entries_thread_id",
        "task_queue_entries",
        ["thread_id"],
    )


def downgrade() -> None:
    """Drop the task-queue entries table."""
    op.drop_index(
        "ix_task_queue_entries_thread_id",
        table_name="task_queue_entries",
    )
    op.drop_table("task_queue_entries")
