"""Record the provider binary and adapter used by each run lane.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add runtime evidence without inventing it for historical runs."""
    op.create_table(
        "provider_runtime_identities",
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=64), nullable=False),
        sa.Column("runtime_authority", sa.String(length=32), nullable=False),
        sa.Column("adapter_name", sa.String(length=128), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("adapter_entry_path", sa.Text(), nullable=False),
        sa.Column("cli_executable_path", sa.Text(), nullable=False),
        sa.Column("cli_version", sa.String(length=64), nullable=False),
        sa.Column("node_version", sa.String(length=64), nullable=True),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("provider_session_id", sa.Text(), nullable=True),
        sa.Column("managed_policy_present", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id", "provider_id", "execution_mode"),
    )


def downgrade() -> None:
    """Remove only the runtime-evidence table."""
    op.drop_table("provider_runtime_identities")
