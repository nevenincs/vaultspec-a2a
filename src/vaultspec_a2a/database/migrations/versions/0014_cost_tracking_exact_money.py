"""Store cost_tracking.estimated_cost as an exact decimal, not a float.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Alembic loads version scripts by SCRIPT LOCATION rather than importing them
# as package members, so a relative import would raise "attempted relative
# import with no known parent package" — the same constraint documented in
# ``env.py``. The custom type is imported rather than re-spelled as concrete
# per-dialect types so the migrated schema and ``Base.metadata`` cannot drift.
from vaultspec_a2a.database.models import (  # absolute-import-ok
    MONEY_SCALE,
    MoneyAmount,
)

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

#: Integer units per dollar in the SQLite representation. Mirrors
#: ``MoneyAmount``'s scaling so the migration and the type cannot disagree.
_UNITS_PER_DOLLAR = 10**MONEY_SCALE


def upgrade() -> None:
    """Convert estimated_cost from IEEE-754 double to an exact decimal type.

    ``estimated_cost`` is SUM-aggregated inside the database, so a float column
    accumulated binary error across a thread's rows against the true decimal
    cost. ``MoneyAmount`` renders a native ``NUMERIC`` on Postgres and a scaled
    ``int64`` on SQLite, which has no decimal type and would otherwise have
    SQLAlchemy round-trip the value through float — reintroducing the defect
    the column change exists to remove.

    The stored representation therefore differs per backend, so the existing
    data must be rewritten, not merely retyped. On SQLite each amount is scaled
    to integer units BEFORE the type change: a bare retype would leave decimal
    values sitting in an INTEGER-affinity column, where the read path's
    unscaling would silently floor every historical cost to zero. Postgres
    needs no rewrite, only an explicit cast, because it stores true decimals on
    both sides of the change.

    Scaling in float here is safe despite the column still being float: the
    largest plausible amount scaled by 1e10 stays far below 2**53, where
    doubles still represent integers exactly.
    """
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE cost_tracking "
                "SET estimated_cost = CAST(ROUND(estimated_cost * :units) AS INTEGER)"
            ).bindparams(units=_UNITS_PER_DOLLAR)
        )

    with op.batch_alter_table("cost_tracking", schema=None) as batch_op:
        batch_op.alter_column(
            "estimated_cost",
            existing_type=sa.Float(),
            type_=MoneyAmount(),
            existing_nullable=False,
            postgresql_using="estimated_cost::numeric",
        )


def downgrade() -> None:
    """Restore the float column, unscaling the SQLite integer representation.

    The inverse order of :func:`upgrade`: the type reverts first so the scaled
    units land back in a float-affinity column, and only then are they divided
    down. Reversing that order would ask an INTEGER-affinity column to hold
    fractional dollars.

    This is lossy in the way the original column was always lossy — returning
    to a double reinstates the imprecision this revision removed — but it is a
    true structural and representational inverse, so the revision reverses
    cleanly.
    """
    with op.batch_alter_table("cost_tracking", schema=None) as batch_op:
        batch_op.alter_column(
            "estimated_cost",
            existing_type=MoneyAmount(),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="estimated_cost::double precision",
        )

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE cost_tracking SET estimated_cost = estimated_cost / :units"
            ).bindparams(units=float(_UNITS_PER_DOLLAR))
        )
