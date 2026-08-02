"""Add stable dispatch identity and renewable claims to control actions.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add lease fields and give every historical action a stable identity."""
    op.add_column(
        "control_actions", sa.Column("dispatch_id", sa.String(), nullable=True)
    )
    op.add_column(
        "control_actions", sa.Column("claim_token", sa.String(), nullable=True)
    )
    op.add_column(
        "control_actions",
        sa.Column("claim_expires_at", sa.DateTime(), nullable=True),
    )
    # ``control_actions.id`` is already a globally unique immutable primary key.
    # Reusing it for pre-0012 rows is deterministic across retries/restarts and
    # avoids backend-specific UUID functions. New repository writes continue to
    # mint an independent dispatch UUID. Backfill before creating the unique index.
    control_actions = sa.table(
        "control_actions",
        sa.column("id", sa.String()),
        sa.column("dispatch_id", sa.String()),
    )
    op.execute(
        control_actions.update()
        .where(control_actions.c.dispatch_id.is_(None))
        .values(dispatch_id=control_actions.c.id)
    )
    # SQLite and Postgres both permit multiple NULL values in a unique index,
    # making every assigned worker receipt identity globally unambiguous.
    op.create_index(
        "ux_control_actions_dispatch_id",
        "control_actions",
        ["dispatch_id"],
        unique=True,
    )


def downgrade() -> None:
    """Remove the dispatch lease fields."""
    op.drop_index("ux_control_actions_dispatch_id", table_name="control_actions")
    op.drop_column("control_actions", "claim_expires_at")
    op.drop_column("control_actions", "claim_token")
    op.drop_column("control_actions", "dispatch_id")
