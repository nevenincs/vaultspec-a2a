"""Persist the accepted run deadline on dispatchable actions.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


class RecoveryDeadlineSchemaIncompatibleError(RuntimeError):
    """Existing accepted actions have no provable original run deadline."""


def _require_empty_store() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM threads LIMIT 1")).first():
        raise RecoveryDeadlineSchemaIncompatibleError(
            "accepted run deadlines require a fresh current application home; "
            "an original deadline cannot be inferred for existing actions"
        )


def upgrade() -> None:
    _require_empty_store()
    op.add_column(
        "control_actions",
        sa.Column("recovery_deadline_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    _require_empty_store()
    op.drop_column("control_actions", "recovery_deadline_at")
