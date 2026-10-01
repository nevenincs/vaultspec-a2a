"""Keep the cache and reasoning token breakdown in cost tracking.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_BREAKDOWN_COLUMNS = ("cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


def upgrade() -> None:
    """Add the breakdown columns, nullable and without a back-fill.

    A row recorded before these columns existed never had its breakdown
    measured, and a lane that does not report one leaves it unknown; writing
    zero for either would assert a count nobody took.
    """
    for column in _BREAKDOWN_COLUMNS:
        op.add_column("cost_tracking", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the breakdown columns."""
    with op.batch_alter_table("cost_tracking") as batch:
        for column in reversed(_BREAKDOWN_COLUMNS):
            batch.drop_column(column)
