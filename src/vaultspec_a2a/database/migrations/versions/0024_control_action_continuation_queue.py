"""Let the control-action journal hold a continuation waiting behind a turn.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Spelled literally rather than imported: a revision describes the schema at
# one moment in the chain, and an import would re-describe it from whatever the
# package means later.
_CONTINUATION_ACTION = "'message_followup_requested'"
_QUEUED = "'queued'"
_POSITION_CONSTRAINT = "ck_control_actions_queue_position_bounded"
_RESERVATION_CONSTRAINT = "ck_control_actions_queued_reservation"
_QUEUED_POSITION_INDEX = "ux_control_actions_queued_position"
_QUEUED_ROW = f"result_status = {_QUEUED}"


class QueuedContinuationPresentError(RuntimeError):
    """A waiting continuation has no shape in the pre-queue schema."""


def upgrade() -> None:
    """Add the queue position and the invariants of a queued reservation.

    Additive over whatever history exists, and deliberately unguarded by an
    empty-store check: every row written before this revision carries no
    position and no queued status, so the new invariants hold for all of them
    without inferring anything about work that was already accepted.

    The column and both checks are applied in one batch because SQLite can
    only gain a CHECK through a table rebuild; the partial index is created
    afterwards, against the rebuilt table.
    """
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.add_column(sa.Column("queue_position", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            _POSITION_CONSTRAINT,
            "queue_position IS NULL OR (queue_position >= 1 "
            f"AND action_type = {_CONTINUATION_ACTION})",
        )
        batch_op.create_check_constraint(
            _RESERVATION_CONSTRAINT,
            f"result_status <> {_QUEUED} OR (queue_position IS NOT NULL "
            "AND graph_receipt_json IS NULL AND applied_at IS NULL)",
        )
    # Partial, so a promoted action may keep the position it was admitted at
    # while the next admission reuses that number.
    op.create_index(
        _QUEUED_POSITION_INDEX,
        "control_actions",
        ["thread_id", "queue_position"],
        unique=True,
        sqlite_where=sa.text(_QUEUED_ROW),
        postgresql_where=sa.text(_QUEUED_ROW),
    )


def downgrade() -> None:
    """Remove the queue position, refusing to discard a waiting continuation.

    A queued row has no representation in the earlier schema, and dropping the
    column would silently turn each one into an ordinary accepted action that
    the dispatcher would then deliver. Refuse instead; drain the queue first.
    """
    waiting = (
        op.get_bind()
        .execute(sa.text(f"SELECT 1 FROM control_actions WHERE {_QUEUED_ROW} LIMIT 1"))
        .first()
    )
    if waiting:
        raise QueuedContinuationPresentError(
            "the control-action journal still holds a queued continuation; the "
            "earlier schema cannot express one, and dropping the column would "
            "release it as ordinary accepted work. Settle or promote every "
            "queued continuation before stepping back past this revision."
        )
    op.drop_index(_QUEUED_POSITION_INDEX, table_name="control_actions")
    with op.batch_alter_table("control_actions") as batch_op:
        batch_op.drop_constraint(_RESERVATION_CONSTRAINT, type_="check")
        batch_op.drop_constraint(_POSITION_CONSTRAINT, type_="check")
        batch_op.drop_column("queue_position")
