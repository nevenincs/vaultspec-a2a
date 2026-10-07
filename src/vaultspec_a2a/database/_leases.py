"""Lease durations, claim tokens and the predicates that say who holds a lease.

The control journal and the recovery schedule claim a row through a token and an
expiry written together; the deletion saga claims through a stamp that lapses.
Every holder answers the same few questions - is the lease free, may this token
take it, is it still live - so they are answered here once, beside the durations
that bound each lease. What a held lease obliges a dispatcher to do belongs to
``control``; this module holds the predicates and the clocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, or_

from .models import ControlActionModel, RecoveryAttemptModel

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import QueryableAttribute
    from sqlalchemy.sql.elements import ColumnElement

__all__ = [
    "CONTROL_ACTION_LEASE",
    "CONTROL_ACTION_LEASE_TTL",
    "DELETION_SAGA_CLAIM_LEASE",
    "RECOVERY_ATTEMPT_LEASE",
    "RECOVERY_CLAIM_TTL",
    "clear_lease",
    "lease_free_from",
    "new_claim_token",
    "require_lease_window",
]

CONTROL_ACTION_LEASE_TTL = timedelta(seconds=90)
"""Fresh ownership window before an unapplied dispatch may be redriven."""

RECOVERY_CLAIM_TTL = timedelta(seconds=45)
"""How long one recovery pass owns a due retry before another pass may claim it."""

DELETION_SAGA_CLAIM_LEASE = timedelta(minutes=5)
"""How long a deletion saga claim survives a pass that never released it.

A pass that ends normally releases its claim when finalization refuses, so this
lease only ever covers a pass killed mid-teardown. A cleanup pass deletes a
checkpoint and unlinks a handful of files - seconds of work - so five minutes is
a wide margin over a healthy pass while still returning a saga abandoned by a
dead process to the next delete request.
"""


@dataclass(frozen=True, slots=True, eq=False)
class _LeaseColumns:
    """The token and expiry columns that together hold one row's lease.

    The two are written and cleared as a pair, so a predicate over a holder is
    always a predicate over both.
    """

    token: QueryableAttribute[str | None]
    expires_at: QueryableAttribute[datetime | None]

    def unheld(self, at: datetime) -> ColumnElement[bool]:
        """Nobody owns the lease at *at*: never taken, released, or lapsed."""
        return or_(
            self.token.is_(None),
            self.expires_at.is_(None),
            self.expires_at <= at,
        )

    def acquirable_by(self, token: str, at: datetime) -> ColumnElement[bool]:
        """*token* may take or renew the lease at *at*."""
        return or_(self.unheld(at), self.token == token)

    def held_by(self, token: str) -> ColumnElement[bool]:
        """*token* is the recorded owner, whether or not its expiry has passed."""
        return self.token == token

    def live(self, at: datetime) -> ColumnElement[bool]:
        """Some owner's lease has not lapsed at *at*."""
        return and_(self.expires_at.is_not(None), self.expires_at > at)

    def granted(self, token: str, expires_at: datetime) -> dict[str, object]:
        """The values that record *token* as the owner until *expires_at*."""
        return {self.token.key: token, self.expires_at.key: expires_at}

    def released(self) -> dict[str, None]:
        """The values that leave nobody owning the lease."""
        return {self.token.key: None, self.expires_at.key: None}


CONTROL_ACTION_LEASE = _LeaseColumns(
    ControlActionModel.claim_token, ControlActionModel.claim_expires_at
)
RECOVERY_ATTEMPT_LEASE = _LeaseColumns(
    RecoveryAttemptModel.claim_token, RecoveryAttemptModel.claim_expires_at
)


def new_claim_token() -> str:
    """Return a fresh token naming one claimant of a lease."""
    return uuid4().hex


def require_lease_window(acquired_at: datetime, claim_expires_at: datetime) -> None:
    """Refuse a lease that would lapse no later than the instant it is taken."""
    if claim_expires_at <= acquired_at:
        raise ValueError("claim_expires_at must be later than acquired_at")


def lease_free_from(expires_at: datetime | None, at: datetime) -> datetime:
    """Return the first instant from *at* on that the lease can be taken again.

    That is *at* itself when nobody holds it, and its expiry while an owner does.
    """
    return at if expires_at is None else max(at, expires_at)


def clear_lease(holder: ControlActionModel | RecoveryAttemptModel) -> None:
    """Drop the lease on a loaded row, leaving nobody owning it."""
    holder.claim_token = None
    holder.claim_expires_at = None
