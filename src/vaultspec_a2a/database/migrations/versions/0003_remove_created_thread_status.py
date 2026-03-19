"""Normalize legacy thread status values after removing `created`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rewrite legacy `created` rows to `submitted`."""
    op.execute("UPDATE threads SET status = 'submitted' WHERE status = 'created'")


def downgrade() -> None:
    """No-op: the legacy `created` rows cannot be reconstructed safely."""
