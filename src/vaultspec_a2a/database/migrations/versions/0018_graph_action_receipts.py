"""Persist immutable graph-action incorporation authority.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


class GraphReceiptSchemaIncompatibleError(RuntimeError):
    """A populated store cannot acquire missing execution evidence retroactively."""


def _require_empty_store() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM threads LIMIT 1")).first():
        raise GraphReceiptSchemaIncompatibleError(
            "graph receipt schema requires a fresh current application home; "
            "existing execution evidence cannot be invented or translated"
        )


def upgrade() -> None:
    _require_empty_store()
    op.add_column(
        "control_actions", sa.Column("graph_receipt_json", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    _require_empty_store()
    op.drop_column("control_actions", "graph_receipt_json")
