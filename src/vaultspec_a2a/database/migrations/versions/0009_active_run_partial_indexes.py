"""Use partial active-run indexes with an index-safe workspace digest.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-20
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_BACKFILL_PAGE = 500
_INDEXES = (
    "ix_threads_active_workspace_feature_order",
    "ix_threads_active_feature_order",
    "ix_threads_active_workspace_order",
    "ix_threads_active_order",
)


def _workspace_key(workspace: str | None) -> str | None:
    if workspace is None:
        return None
    return hashlib.sha256(workspace.encode("utf-8")).hexdigest()


def _drop_active_indexes() -> None:
    for name in _INDEXES:
        op.drop_index(name, table_name="threads")


def upgrade() -> None:
    """Replace full-history/raw-path indexes with partial digest indexes."""
    op.add_column("threads", sa.Column("workspace_key", sa.String(64)))
    connection = op.get_bind()
    cursor = connection.execute(
        sa.text("SELECT id, workspace_root FROM threads ORDER BY id")
    )
    while rows := cursor.fetchmany(_BACKFILL_PAGE):
        connection.execute(
            sa.text(
                "UPDATE threads SET workspace_key = :workspace_key "
                "WHERE id = :thread_id"
            ),
            [
                {
                    "thread_id": row.id,
                    "workspace_key": _workspace_key(row.workspace_root),
                }
                for row in rows
            ],
        )

    _drop_active_indexes()
    partial = {
        "sqlite_where": sa.text("is_active IS 1"),
        "postgresql_where": sa.text("is_active IS true"),
    }
    op.create_index(
        "ix_threads_active_order",
        "threads",
        [sa.text("created_at DESC"), sa.text("id DESC")],
        **partial,
    )
    op.create_index(
        "ix_threads_active_workspace_order",
        "threads",
        ["workspace_key", sa.text("created_at DESC"), sa.text("id DESC")],
        **partial,
    )
    op.create_index(
        "ix_threads_active_feature_order",
        "threads",
        ["feature_tag", sa.text("created_at DESC"), sa.text("id DESC")],
        **partial,
    )
    op.create_index(
        "ix_threads_active_workspace_feature_order",
        "threads",
        [
            "workspace_key",
            "feature_tag",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        **partial,
    )


def downgrade() -> None:
    """Restore the v8 full-history raw-workspace indexes."""
    _drop_active_indexes()
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
        "ix_threads_active_feature_order",
        "threads",
        [
            "is_active",
            "feature_tag",
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
    op.drop_column("threads", "workspace_key")
