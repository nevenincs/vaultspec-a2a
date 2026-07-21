"""Retention vocabulary and the declaration every artifact seam carries.

A durable artifact whose lifetime nobody declared is one nobody can enumerate,
and an artifact nobody can enumerate is one no reaper can find.  That is the
shape behind every unbounded-growth defect this package exists to prevent: the
cleanup usually existed and simply could not see its target.

So the unit here is a declaration, not a sweeper.  Each seam that creates a
durable artifact states where it lands, which component owns it, how long it
lives, and what enforces that lifetime.  Permanence stays available - some
artifacts genuinely should outlive every process that reads them - but it must
be chosen and justified rather than arrived at by omission, which is what
:attr:`RetentionDisposition.PERMANENT` requiring a reason enforces.

The declaration is deliberately inert.  It records intent at the seam so intent
is reviewable and enumerable; it does not delete anything, and nothing here
should ever acquire the authority to.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "ArtifactDeclaration",
    "RetentionDeclarationError",
    "RetentionDisposition",
]


class RetentionDisposition(StrEnum):
    """How long a declared artifact is allowed to live.

    The set is intentionally small.  A vocabulary broad enough to describe every
    nuance is one where two seams with identical behaviour pick different words,
    and the point of declaring is to make seams comparable.
    """

    BOUNDED_BY_SIZE = "bounded-by-size"
    """Capped by bytes or generation count, e.g. a rotating log."""

    BOUNDED_BY_AGE = "bounded-by-age"
    """Removed once older than a stated threshold."""

    SESSION_SCOPED = "session-scoped"
    """Removed when its owning run, session, or process ends."""

    PERMANENT = "permanent"
    """Kept indefinitely on purpose; requires a stated reason."""


class RetentionDeclarationError(ValueError):
    """Raised when a declaration is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ArtifactDeclaration:
    """What one seam creates, and who is responsible for it afterwards.

    Attributes:
        name: Stable identifier for the artifact class, kebab-case.
        root: Where it lands, as a path expression rather than a resolved path
            so a declaration stays true across hosts and profiles.
        owner: The component answerable for the artifact's lifetime.
        disposition: How long it is allowed to live.
        mechanism: What actually enforces the disposition.  For
            :attr:`RetentionDisposition.PERMANENT` this states what keeps the
            artifact bounded instead, or says plainly that nothing does.
        reason: Why permanence is correct.  Required for, and only meaningful
            on, a permanent declaration.

    Raises:
        RetentionDeclarationError: If any required field is blank, if a
            permanent declaration carries no reason, or if a non-permanent one
            supplies a reason that would never be read.
    """

    name: str
    root: str
    owner: str
    disposition: RetentionDisposition
    mechanism: str
    reason: str | None = None

    def __post_init__(self) -> None:
        """Reject a declaration that cannot be acted on."""
        for field_name in ("name", "root", "owner", "mechanism"):
            if not str(getattr(self, field_name)).strip():
                raise RetentionDeclarationError(
                    f"artifact declaration requires a non-empty {field_name}"
                )
        has_reason = bool(self.reason and self.reason.strip())
        if self.disposition is RetentionDisposition.PERMANENT and not has_reason:
            raise RetentionDeclarationError(
                f"artifact {self.name!r} is declared permanent without a reason: "
                "permanence is a choice that must be justified, not a default"
            )
        if self.disposition is not RetentionDisposition.PERMANENT and has_reason:
            raise RetentionDeclarationError(
                f"artifact {self.name!r} supplies a permanence reason but is "
                f"declared {self.disposition.value}; the reason would never be read"
            )

    @property
    def is_bounded(self) -> bool:
        """Whether something is expected to remove this artifact eventually."""
        return self.disposition is not RetentionDisposition.PERMANENT
