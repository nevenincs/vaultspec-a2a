"""Retire the tables, columns and action types nothing reads or writes.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Spelled literally rather than imported: a revision describes the schema at
# one moment in the chain, and an import would re-describe it from whatever the
# package means later.
_CURRENT_ACTIONS = (
    "'ingest', 'resume', 'cancel', 'permission_request_created', "
    "'permission_response_submitted', 'permission_response_applied', "
    "'message_followup_requested', 'message_followup_applied'"
)
_RETIRED_ACTIONS = "'repair_started', 'repair_finished'"
_PRIOR_ACTIONS = f"{_CURRENT_ACTIONS}, {_RETIRED_ACTIONS}"
_WRITER_ACTION_CONSTRAINT = "ck_threads_writer_action_type_current"
_JOURNAL_ACTION_CONSTRAINT = "ck_control_actions_action_type_current"

# The partial active-run indexes, by the selectors each orders ahead of the
# newest-first tail. A batch rebuild of ``threads`` would reflect them back
# ascending, since SQLite reflection cannot report an index's direction, so
# they are dropped before the rebuild and recreated exactly as 0009 made them.
_ACTIVE_INDEXES: dict[str, tuple[str, ...]] = {
    "ix_threads_active_order": (),
    "ix_threads_active_workspace_order": ("workspace_key",),
    "ix_threads_active_feature_order": ("feature_tag",),
    "ix_threads_active_workspace_feature_order": ("workspace_key", "feature_tag"),
}
_ACTIVE_ROW = "is_active IS 1"


class RetiredActionTypePresentError(RuntimeError):
    """A stored row names an action type the narrowed vocabulary cannot hold."""


def _refuse_retired_action_rows() -> None:
    retired = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM control_actions "
                f"WHERE action_type IN ({_RETIRED_ACTIONS}) "
                "UNION ALL SELECT 1 FROM threads "
                f"WHERE writer_action_type IN ({_RETIRED_ACTIONS}) "
                "UNION ALL SELECT 1 FROM recovery_attempts "
                f"WHERE action_type IN ({_RETIRED_ACTIONS}) "
                "LIMIT 1"
            )
        )
        .first()
    )
    if retired:
        raise RetiredActionTypePresentError(
            "a stored control action, run writer or recovery attempt names a "
            "repair action type this revision retires. No release ever wrote "
            "one, so the store was written by a foreign generation; create a "
            "fresh current application home rather than stepping it forward."
        )


def _drop_active_indexes() -> None:
    for name in _ACTIVE_INDEXES:
        op.drop_index(name, table_name="threads")


def _create_active_indexes() -> None:
    for name, selectors in _ACTIVE_INDEXES.items():
        op.create_index(
            name,
            "threads",
            [*selectors, sa.text("created_at DESC"), sa.text("id DESC")],
            sqlite_where=sa.text(_ACTIVE_ROW),
        )


def _threads_with_prior_vocabulary() -> sa.Table:
    """The ``threads`` structure the downgrade rebuilds, minus the restored columns.

    Stated rather than reflected for one reason: the write-authority CHECKs must
    come back attached to their columns, as 0017 added them. A reflected
    rebuild restates every CHECK at table level, and SQLite will not drop a
    column that a table-level CHECK names, so 0017's own downgrade could no
    longer remove the authority columns. The descending partial indexes are
    dropped and recreated around the rebuild rather than declared here.
    """
    return sa.Table(
        "threads",
        sa.MetaData(),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("thread_metadata", sa.Text(), nullable=True),
        sa.Column("nickname", sa.String(), nullable=True),
        sa.Column("team_preset", sa.String(), nullable=True),
        sa.Column(
            "repair_status", sa.String(), nullable=False, server_default="healthy"
        ),
        sa.Column("repair_reason", sa.Text(), nullable=True),
        sa.Column(
            "execution_readiness",
            sa.String(),
            nullable=False,
            server_default="healthy",
        ),
        sa.Column("last_requested_action", sa.String(), nullable=True),
        sa.Column("last_applied_action", sa.String(), nullable=True),
        sa.Column("approval_status", sa.String(), nullable=True),
        sa.Column("approval_request_id", sa.String(), nullable=True),
        sa.Column("approval_response_action_id", sa.String(), nullable=True),
        sa.Column("approval_updated_at", sa.DateTime(), nullable=True),
        sa.Column("workspace_root", sa.String(4096), nullable=True),
        sa.Column("feature_tag", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("workspace_key", sa.String(64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("provider_condition", sa.String(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=True),
        sa.Column(
            "run_revision",
            sa.Integer(),
            sa.CheckConstraint(
                "run_revision >= 0", name="ck_threads_run_revision_nonnegative"
            ),
            nullable=False,
        ),
        sa.Column(
            "writer_generation",
            sa.Integer(),
            sa.CheckConstraint(
                "writer_generation >= 1",
                name="ck_threads_writer_generation_positive",
            ),
            nullable=False,
        ),
        sa.Column(
            "writer_action_type",
            sa.String(length=32),
            sa.CheckConstraint(
                f"writer_action_type IN ({_PRIOR_ACTIONS})",
                name=_WRITER_ACTION_CONSTRAINT,
            ),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_threads_nickname", "nickname", unique=True),
        sa.Index(
            "ux_threads_writer_action_receipt_id",
            "writer_action_receipt_id",
            unique=True,
        ),
    )


def upgrade() -> None:
    """Drop the dead tables and columns and narrow the action-type CHECKs.

    Every dropped column was either never written or written and never read,
    so nothing a reader relies on is lost. The two action-type CHECKs narrow to
    the current vocabulary; the refusal runs first, before any table is
    touched, so a store holding a retired type is left exactly as it was.

    Column drops and CHECK changes rebuild their tables, as SQLite needs. The
    ``threads`` rebuild runs between the drop and the recreation of its
    descending partial indexes; every other index survives the rebuilds
    through reflection.
    """
    _refuse_retired_action_rows()
    op.drop_index("ix_task_queue_entries_thread_id", table_name="task_queue_entries")
    op.drop_table("task_queue_entries")
    op.drop_index("ix_artifacts_thread_id", table_name="artifacts")
    op.drop_table("artifacts")
    with op.batch_alter_table("thread_execution_state") as batch_op:
        batch_op.drop_column("interrupt_types_json")
        batch_op.drop_column("recovery_epoch")
        batch_op.drop_column("snapshot_created_at")
    with op.batch_alter_table("permission_requests") as batch_op:
        batch_op.drop_column("worker_generation")
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.drop_column("worker_generation")
        batch_op.drop_constraint(_JOURNAL_ACTION_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _JOURNAL_ACTION_CONSTRAINT, f"action_type IN ({_CURRENT_ACTIONS})"
        )
    _drop_active_indexes()
    with op.batch_alter_table("threads") as batch_op:
        batch_op.drop_column("approval_reason")
        batch_op.drop_column("repair_generation")
        batch_op.drop_column("recovery_epoch")
        batch_op.drop_constraint(_WRITER_ACTION_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _WRITER_ACTION_CONSTRAINT, f"writer_action_type IN ({_CURRENT_ACTIONS})"
        )
    _create_active_indexes()


def downgrade() -> None:
    """Restore the retired schema, empty of what the upgrade discarded.

    The tables come back empty and the columns at their defaults: the values
    the upgrade dropped were never read, and a downgrade cannot recover them.
    ``worker_generation`` and ``interrupt_types_json`` were required without a
    server default; each regains one here, because the rows already present
    need a value in the restored column. Widening the CHECKs back to the prior
    vocabulary leaves every stored row valid.
    """
    _drop_active_indexes()
    with op.batch_alter_table(
        "threads", copy_from=_threads_with_prior_vocabulary(), recreate="always"
    ) as batch_op:
        batch_op.add_column(sa.Column("approval_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "repair_generation", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "recovery_epoch", sa.Integer(), nullable=False, server_default="0"
            )
        )
    _create_active_indexes()
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "worker_generation", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.drop_constraint(_JOURNAL_ACTION_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _JOURNAL_ACTION_CONSTRAINT, f"action_type IN ({_PRIOR_ACTIONS})"
        )
    with op.batch_alter_table("permission_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "worker_generation", sa.Integer(), nullable=False, server_default="0"
            )
        )
    with op.batch_alter_table("thread_execution_state") as batch_op:
        batch_op.add_column(
            sa.Column("snapshot_created_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "recovery_epoch", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "interrupt_types_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
    )
    op.create_index("ix_artifacts_thread_id", "artifacts", ["thread_id"])
    op.create_table(
        "task_queue_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("feature_tag", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("plan_changeset_id", sa.String(), nullable=True),
        sa.Column("plan_step_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "position",
            name="uq_task_queue_entries_thread_id_position",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "task_key",
            name="uq_task_queue_entries_thread_id_task_key",
        ),
    )
    op.create_index(
        "ix_task_queue_entries_thread_id",
        "task_queue_entries",
        ["thread_id"],
    )
