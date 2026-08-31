"""Allow a permission-decision log row to carry no agent attribution.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

#: What a downgrade writes where the upgrade permitted no attribution. Bracketed
#: so it cannot be mistaken for a real agent identifier, and non-empty so the
#: restored NOT NULL constraint holds.
_UNATTRIBUTED = "<unattributed>"


def upgrade() -> None:
    """Make ``permission_logs.agent_id`` nullable.

    The audit log records which tool call was approved or rejected on which run.
    The deciding identity is not knowable at the seam that records it: the agent
    whose call was gated is never captured upstream, and the responder is not
    threaded through as an authenticated identity. A required column therefore
    forces either a fabricated attribution or no audit record at all, and an
    unattributed decision is still the security answer that is missing today.
    """
    with op.batch_alter_table("permission_logs") as batch_op:
        batch_op.alter_column("agent_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Restore the NOT NULL constraint, back-filling rows that have no agent.

    A downgrade is a schema operation and must not destroy audit rows, so rows
    the upgrade permitted to have no attribution are marked rather than deleted.
    The back-fill runs first: the constraint cannot be restored while a NULL
    remains.
    """
    op.execute(
        sa.text(
            "UPDATE permission_logs SET agent_id = :marker WHERE agent_id IS NULL"
        ).bindparams(marker=_UNATTRIBUTED)
    )
    with op.batch_alter_table("permission_logs") as batch_op:
        batch_op.alter_column("agent_id", existing_type=sa.String(), nullable=False)
