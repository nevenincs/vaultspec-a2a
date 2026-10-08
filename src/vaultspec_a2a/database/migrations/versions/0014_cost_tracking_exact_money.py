"""Store cost_tracking.estimated_cost as an exact decimal, not a float.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-03
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, override

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect
    from sqlalchemy.types import TypeEngine

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

#: Decimal places this revision keeps for a monetary amount, frozen here.
#: Ten places resolve to 1e-10 USD, below the cheapest single priceable token.
_MONEY_SCALE = 10

#: Integer units per dollar in the SQLite representation. Derived from the
#: frozen scale, so the rewrite below and the column type cannot disagree.
_UNITS_PER_DOLLAR = 10**_MONEY_SCALE


class MoneyAmount(sa.types.TypeDecorator[Decimal]):
    """The exact-decimal column type this revision installs, frozen in place.

    A deliberate copy of what ``database.models`` declared when this revision
    shipped, and NOT an import of whatever it declares now. A revision states
    the schema at ONE moment in the chain: importing the live type would let a
    later model change silently rewrite DDL that every existing store has
    already replayed, and would break this script outright the day the symbol
    is deleted. The duplication is the migration framework's rule rather than a
    defect, so the duplication guard exempts it.

    Only the DDL rendering is load-bearing here. This revision rewrites the
    stored amounts in SQL rather than through the ORM, so no value is ever
    bound or loaded through this type; the bind and result processors the live
    type carried are therefore no part of what the schema froze.
    """

    impl = sa.Numeric
    cache_ok = True

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Render scaled-integer storage, as the original type did.

        SQLite has no decimal type and SQLAlchemy's plain ``Numeric`` copes by
        round-tripping through ``float``, so the amount is stored as an exact
        integer count of 1e-``_MONEY_SCALE`` dollar units instead.
        """
        return dialect.type_descriptor(sa.BigInteger())


#: Back-fill marker used only when downgrading restores the NOT NULL lane
#: columns. Bracketed so it cannot be confused with a real provider or model
#: name, and never written by the upgrade path or by production code.
_UNKNOWN = "<unknown>"


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
        # The lane identity becomes optional in the same revision that makes the
        # table writable for the first time. The accounting writer records the
        # provider and model the invoked instance actually declared; when it
        # declares neither, NULL states that honestly. Requiring a value would
        # force a stand-in string that reads as a real provider lane, so the
        # constraint would buy tidiness at the cost of truthfulness.
        batch_op.alter_column("provider", existing_type=sa.String(), nullable=True)
        batch_op.alter_column("model", existing_type=sa.String(), nullable=True)


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

    Restoring the NOT NULL lane columns has to contend with rows this revision
    permitted to have none. They are back-filled with a plainly synthetic marker
    rather than deleted: a downgrade is a schema operation and must not destroy
    measured token counts, and the marker is chosen to be obviously not a lane
    name so it cannot be mistaken for one on a later upgrade.
    """
    op.execute(
        sa.text(
            f"UPDATE cost_tracking SET provider = '{_UNKNOWN}' WHERE provider IS NULL"
        )
    )
    op.execute(
        sa.text(f"UPDATE cost_tracking SET model = '{_UNKNOWN}' WHERE model IS NULL")
    )

    with op.batch_alter_table("cost_tracking", schema=None) as batch_op:
        batch_op.alter_column(
            "estimated_cost",
            existing_type=MoneyAmount(),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="estimated_cost::double precision",
        )
        batch_op.alter_column("provider", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("model", existing_type=sa.String(), nullable=False)

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE cost_tracking SET estimated_cost = estimated_cost / :units"
            ).bindparams(units=float(_UNITS_PER_DOLLAR))
        )
