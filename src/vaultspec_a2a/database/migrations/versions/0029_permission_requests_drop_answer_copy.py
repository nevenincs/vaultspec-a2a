"""Retire the permission request row's second copy of the answer.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# The storage 0002 installed for both columns: a nullable, unbounded string.
# Spelled concretely rather than imported, as every revision spells its schema.
_ANSWER_COPY_STORAGE = sa.String()

#: The two columns, newest-first for the downgrade so the restored table lists
#: them in the order 0002 declared them.
_ANSWER_COPY_COLUMNS: tuple[str, ...] = ("response_option_id", "idempotency_key")


def upgrade() -> None:
    """Drop the answer columns, leaving the request's own lifecycle.

    Neither column had a reader. The settlement reads the answered option off the
    frozen envelope of the ACCEPTED response action - deliberately, so that a row
    rewritten after acceptance cannot change which option a run is settled under -
    and ``permission_logs`` is the durable record of the decision itself. The
    journal key belongs to the control action it names, which carries its own.

    What remained was write-only storage of a fact owned elsewhere, and a future
    reader that trusted it could be told a different answer than the one the run
    was actually resumed with. Nothing is lost: every value either column held is
    still readable from the response action and the decision log.

    The batch rebuild SQLite needs is also what keeps the surrounding schema
    intact, since the table's two indexes are recreated with it.
    """
    with op.batch_alter_table("permission_requests", schema=None) as batch_op:
        for column in _ANSWER_COPY_COLUMNS:
            batch_op.drop_column(column)


def downgrade() -> None:
    """Restore both nullable columns, empty.

    A true inverse of the drop rather than a reconstruction: the columns come
    back exactly as 0002 declared them - nullable, unbounded, defaultless - and
    hold NULL. Back-filling them from the response journal would be a different
    operation, writing values this revision never removed from there, and a
    downgrade that invents data is worse than one that restores the shape.
    """
    with op.batch_alter_table("permission_requests", schema=None) as batch_op:
        for column in _ANSWER_COPY_COLUMNS:
            batch_op.add_column(sa.Column(column, _ANSWER_COPY_STORAGE, nullable=True))
