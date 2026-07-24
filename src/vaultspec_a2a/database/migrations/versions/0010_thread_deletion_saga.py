"""Add the durable cross-store thread deletion saga.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the outbox table that makes cross-store thread deletion atomic."""
    op.create_table(
        "thread_deletion_saga",
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("thread_id"),
    )


def downgrade() -> None:
    """Remove the cross-store thread deletion saga table."""
    op.drop_table("thread_deletion_saga")
