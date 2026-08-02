"""Add the durable provider-condition column to threads.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add threads.provider_condition: the typed counterpart to failure_reason.

    Additive and nullable, with no default and no back-fill. A run that failed
    before this column existed genuinely carries no classification, and writing
    one for it would assert we classified runs we never observed - the same
    manufactured certainty the reason column exists to remove.

    Deliberately NOT NULL-free by constraint rather than by accident: the
    invariant that every NEW failure carries a condition is enforced where the
    terminal status is written, not here. A database constraint would convert a
    classification bug into a write crash that loses the run's outcome
    altogether, which is worse than persisting an honest floor value.

    Kept as an unconstrained string rather than a native enum: the vocabulary is
    a wire contract shared with a second repository and is additive-only, so a
    new member must never require a schema migration to become storable.
    """
    op.add_column(
        "threads", sa.Column("provider_condition", sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Drop the provider-condition column."""
    op.drop_column("threads", "provider_condition")
