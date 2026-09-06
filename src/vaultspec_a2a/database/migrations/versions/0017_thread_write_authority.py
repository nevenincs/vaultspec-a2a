"""Install current run write authority on empty thread stores only.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


class PopulatedThreadStoreIncompatibleError(RuntimeError):
    """A store with threads cannot acquire truthful authority retrospectively."""


def _refuse_populated_store(operation: str) -> None:
    row = op.get_bind().execute(sa.text("SELECT 1 FROM threads LIMIT 1")).first()
    if row is not None:
        raise PopulatedThreadStoreIncompatibleError(
            f"cannot {operation} thread write authority for a populated store; "
            "create a fresh current application home"
        )


def upgrade() -> None:
    """Install required authority without inventing values for existing runs."""
    _refuse_populated_store("install")
    op.add_column(
        "threads",
        sa.Column(
            "run_revision",
            sa.Integer(),
            sa.CheckConstraint(
                "run_revision >= 0", name="ck_threads_run_revision_nonnegative"
            ),
            nullable=False,
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "writer_generation",
            sa.Integer(),
            sa.CheckConstraint(
                "writer_generation >= 1",
                name="ck_threads_writer_generation_positive",
            ),
            nullable=False,
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "writer_action_type",
            sa.String(length=32),
            sa.CheckConstraint(
                "writer_action_type IN "
                "('ingest', 'resume', 'cancel', 'permission_request_created', "
                "'permission_response_submitted', 'permission_response_applied', "
                "'message_followup_requested', 'message_followup_applied', "
                "'repair_started', 'repair_finished')",
                name="ck_threads_writer_action_type_current",
            ),
            nullable=False,
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "writer_action_receipt_id",
            sa.String(length=64),
            sa.CheckConstraint(
                "length(trim(writer_action_receipt_id)) >= 1 "
                "AND length(writer_action_receipt_id) <= 64",
                name="ck_threads_writer_action_receipt_id_bounded",
            ),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_threads_writer_action_receipt_id",
        "threads",
        ["writer_action_receipt_id"],
        unique=True,
    )


def downgrade() -> None:
    """Remove authority only when no run identity can be destroyed."""
    _refuse_populated_store("remove")
    op.drop_index("ux_threads_writer_action_receipt_id", table_name="threads")
    op.drop_column("threads", "writer_action_receipt_id")
    op.drop_column("threads", "writer_action_type")
    op.drop_column("threads", "writer_generation")
    op.drop_column("threads", "run_revision")
