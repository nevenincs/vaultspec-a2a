"""Add the durable reconnect-cursor column to threads.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add threads.last_sequence: the durable SSE/WebSocket reconnect cursor.

    The live value lives only on the gateway's in-memory EventAggregator and
    is pruned the moment a run settles, so a REST read after settle -- the
    only moment a reconnecting client's cursor comparison matters -- always
    answered 0 (F19). Captured at the same terminal-status write as
    failure_reason/provider_condition/repair_status, before the prune runs.

    Additive and nullable, with no default and no back-fill, on the same
    reasoning as 0013's provider_condition: a run that settled before this
    column existed genuinely has no captured cursor, and 0 is itself a
    legitimate value for a thread with truly zero relayed events -- a
    default of 0 would make "never captured" indistinguishable from
    "captured as zero", the exact failure this column exists to close.

    A plain ``op.add_column`` rather than a batch alter: this table's own
    comment (``database/models.py``, beside the ``status`` column) records
    that a batch rebuild on SQLite silently rewrites this table's four
    partial ``ix_threads_active_*`` indexes from DESC to ASC, undetectably
    to the schema-parity suite. Adding a nullable column with no
    server-side default needs no rebuild on SQLite or Postgres, so that
    trap does not apply here -- but the choice is deliberate, not an
    oversight, in case a later revision on this table is tempted to widen
    the scope.
    """
    op.add_column("threads", sa.Column("last_sequence", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the last-sequence column."""
    op.drop_column("threads", "last_sequence")
