"""Hold a bounded per-run log of the progress frames a run emitted.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the replay log, additively over whatever history exists.

    No empty-store guard, unlike the revisions that introduced execution
    evidence: a run that settled before this table existed genuinely emitted no
    retained frames, and an absent window is the honest answer for it rather
    than a schema this store cannot acquire retroactively.

    The foreign key is left UNNAMED, as every other ``thread_id`` edge in this
    schema is, so a later SQLite batch rebuild can target it through Alembic's
    per-migration naming convention.
    """
    op.create_table(
        "run_events",
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.CheckConstraint("sequence >= 1", name="ck_run_events_sequence_positive"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id", "sequence"),
    )
    op.create_index("ix_run_events_created_at", "run_events", ["created_at"])


def downgrade() -> None:
    """Drop the replay log and its sweep index."""
    op.drop_index("ix_run_events_created_at", table_name="run_events")
    op.drop_table("run_events")
