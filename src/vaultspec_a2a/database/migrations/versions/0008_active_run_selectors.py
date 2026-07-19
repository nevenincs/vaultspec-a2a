"""Add indexed active-run discovery selectors.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-19
"""

from __future__ import annotations

import json
import os

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_BACKFILL_PAGE = 500


def _selectors(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, RecursionError, TypeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    workspace = value.get("workspace_root")
    feature = value.get("feature_tag")
    if (
        not isinstance(workspace, str)
        or not os.path.isabs(workspace)
        or not 1 <= len(workspace) <= 4096
    ):
        workspace = None
    else:
        workspace = os.path.normcase(os.path.realpath(workspace))
    if not isinstance(feature, str) or not 1 <= len(feature) <= 128:
        feature = None
    return workspace, feature


def upgrade() -> None:
    """Project selectors once, then add covering indexes for direct discovery."""
    op.add_column("threads", sa.Column("workspace_root", sa.String(4096)))
    op.add_column("threads", sa.Column("feature_tag", sa.String(128)))
    op.add_column(
        "threads",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE threads SET is_active = false "
            "WHERE status IN ('archived', 'cancelled', 'completed', 'failed')"
        )
    )

    connection = op.get_bind()
    cursor = connection.execute(
        sa.text("SELECT id, thread_metadata FROM threads ORDER BY id")
    )
    while rows := cursor.fetchmany(_BACKFILL_PAGE):
        updates = []
        for row in rows:
            workspace, feature = _selectors(row.thread_metadata)
            updates.append(
                {
                    "thread_id": row.id,
                    "workspace_root": workspace,
                    "feature_tag": feature,
                }
            )
        connection.execute(
            sa.text(
                "UPDATE threads SET workspace_root = :workspace_root, "
                "feature_tag = :feature_tag WHERE id = :thread_id"
            ),
            updates,
        )

    op.create_index(
        "ix_threads_active_order",
        "threads",
        ["is_active", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_threads_active_workspace_order",
        "threads",
        [
            "is_active",
            "workspace_root",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_threads_active_workspace_feature_order",
        "threads",
        [
            "is_active",
            "workspace_root",
            "feature_tag",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )


def downgrade() -> None:
    """Remove active-run selector indexes and projection columns."""
    op.drop_index("ix_threads_active_workspace_feature_order", table_name="threads")
    op.drop_index("ix_threads_active_workspace_order", table_name="threads")
    op.drop_index("ix_threads_active_order", table_name="threads")
    op.drop_column("threads", "is_active")
    op.drop_column("threads", "feature_tag")
    op.drop_column("threads", "workspace_root")
