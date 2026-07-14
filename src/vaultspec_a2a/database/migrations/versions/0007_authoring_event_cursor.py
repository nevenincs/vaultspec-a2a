"""Add authoring lifecycle-stream cursor table (ADR R3, P03.S07).

Persists the last outbox sequence the verdict subscriber has processed from
the engine's ``GET /authoring/v1/events`` stream, so a gateway restart resumes
the stream from where it left off instead of replaying from zero.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the authoring event-cursor table."""
    op.create_table(
        "authoring_event_cursor",
        sa.Column("subscriber_id", sa.String(), nullable=False),
        sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("subscriber_id"),
    )


def downgrade() -> None:
    """Drop the authoring event-cursor table."""
    op.drop_table("authoring_event_cursor")
