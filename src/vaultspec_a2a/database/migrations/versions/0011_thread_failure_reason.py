"""Add the durable terminal failure-reason column to threads.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add threads.failure_reason: the capped, single-line terminal-fail reason.

    Additive and nullable: existing rows (and every non-failed terminal
    transition) simply carry NULL. Populated alongside a FAILED status write
    from the same capped single-line text the SSE relay already surfaces
    (ingest's classified reason, a compile-time refusal's exception text, or
    the ingest-stall watchdog's reason) so a reloaded panel — which reads only
    this durable record, never the non-authoritative SSE stream — recovers
    the SAME reason a live-connected client saw, not a bare "failed".
    """
    op.add_column("threads", sa.Column("failure_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the terminal failure-reason column."""
    op.drop_column("threads", "failure_reason")
