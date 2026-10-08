"""Retire cost_tracking.estimated_cost, a price nothing ever measured.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# The storage 0014 installed: an exact integer count of 1e-10 dollar units.
# Spelled concretely rather than imported, as every revision spells its schema,
# and necessarily so here - the custom type that rendered it is frozen inside
# 0014 and is no longer a live symbol anywhere.
_MONEY_STORAGE = sa.BigInteger()

# The only value the column ever held. The accounting writer never set it, so
# every row carries the model's structural zero; the downgrade therefore
# restores a true inverse rather than inventing data.
_UNWRITTEN = "0"


def upgrade() -> None:
    """Drop the price column, keeping every measured token count.

    The column recorded a cost the system never measured. Every served lane is
    a subscription-authenticated CLI agent and the project holds no rate table
    for any model, so nothing could price a token and the writer deliberately
    left the column alone. What remained was worse than an absent column: a
    structural zero that a reader can take for a measured one, and a SUM over
    structural zeros that reads back as a measured total of zero dollars.

    The batch rebuild SQLite needs is also what keeps the surrounding schema
    intact, since the table's two indexes are recreated with it.
    """
    with op.batch_alter_table("cost_tracking", schema=None) as batch_op:
        batch_op.drop_column("estimated_cost")


def downgrade() -> None:
    """Restore the NOT NULL scaled-integer column, back-filled with its zero.

    Re-added in two steps because the constraint and the default cannot both be
    right at once: SQLite can only add a NOT NULL column by giving existing rows
    a default, and the column 0027 holds declares none. So the default carries
    the rebuild and is then dropped, leaving exactly the column 0014 left behind
    rather than one that merely holds the same values.
    """
    with op.batch_alter_table("cost_tracking", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "estimated_cost",
                _MONEY_STORAGE,
                nullable=False,
                server_default=sa.text(_UNWRITTEN),
            )
        )

    with op.batch_alter_table("cost_tracking", schema=None) as batch_op:
        batch_op.alter_column(
            "estimated_cost",
            existing_type=_MONEY_STORAGE,
            existing_nullable=False,
            server_default=None,
        )
