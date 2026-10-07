"""Run write authority: the identity that elects one durable run-state writer.

Layer 1 module. The value, its successor rule and its ownership predicate are
pure; persistence and the SQL form of the predicate live in ``database``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .enums import ControlActionType, ThreadStatus

__all__ = [
    "RECEIPT_ID_MAX_LENGTH",
    "RunWriteAuthority",
    "ThreadWriteExpectation",
]

RECEIPT_ID_MAX_LENGTH = 64
"""Longest action receipt id the run row, the journal and their evidence admit."""


def _is_integer_at_least(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


@dataclass(frozen=True, slots=True)
class RunWriteAuthority:
    """Complete identity required to elect one durable run-state writer.

    This value is deliberately separate from the thread row model until the
    current-only migration installs all four columns atomically. Mapping the
    fields ahead of that migration would make the current schema unreadable;
    making them nullable or defaulted would instead manufacture authority for
    rows that never carried it. The value contains only concurrency and receipt
    identity. Checkpoint state and transcript content remain in their existing
    stores, and credentials have no field here.
    """

    run_revision: int
    writer_generation: int
    action_type: ControlActionType
    action_receipt_id: str

    def __post_init__(self) -> None:
        """Reject incomplete or structurally invalid current authority."""
        # Runtime checks also defend against deserialized values that bypass
        # the static types; bool is not a valid revision or generation.
        if not _is_integer_at_least(self.run_revision, 0):
            raise ValueError("run_revision must be a non-negative integer")
        if not _is_integer_at_least(self.writer_generation, 1):
            raise ValueError("writer_generation must be a positive integer")
        if not isinstance(cast("object", self.action_type), ControlActionType):
            raise TypeError("action_type must be a ControlActionType")
        if not isinstance(cast("object", self.action_receipt_id), str):
            raise TypeError("action_receipt_id must be a string")
        if (
            not self.action_receipt_id.strip()
            or len(self.action_receipt_id) > RECEIPT_ID_MAX_LENGTH
        ):
            raise ValueError(
                "action_receipt_id cannot be blank and must contain at most "
                f"{RECEIPT_ID_MAX_LENGTH} characters"
            )

    def owned_by(
        self,
        action_type: ControlActionType | str,
        action_receipt_id: str | None,
        *,
        writer_generation: int | None = None,
        run_revision: int | None = None,
        exact_revision: bool = True,
    ) -> bool:
        """Return whether the named action holds this authority.

        The action type and receipt id identify the writer. Evidence that also
        records a generation or a revision pins those too. ``exact_revision``
        set false admits a revision at or before this one, because a state-only
        election advances the revision while the same action stays the writer.
        """
        if (
            self.action_type != action_type
            or self.action_receipt_id != action_receipt_id
        ):
            return False
        if (
            writer_generation is not None
            and writer_generation != self.writer_generation
        ):
            return False
        if run_revision is None:
            return True
        if exact_revision:
            return run_revision == self.run_revision
        return run_revision <= self.run_revision

    def successor(
        self, *, action_type: ControlActionType, action_receipt_id: str
    ) -> RunWriteAuthority:
        """Return the authority the named action holds once it wins an election.

        The revision always advances by one. The writer generation advances only
        when a different action takes over, so a state-only election by the
        current writer keeps its generation.
        """
        if not isinstance(cast("object", action_type), ControlActionType):
            raise TypeError("action_type must be a ControlActionType")
        same_action = self.owned_by(action_type, action_receipt_id)
        return RunWriteAuthority(
            run_revision=self.run_revision + 1,
            writer_generation=(
                self.writer_generation if same_action else self.writer_generation + 1
            ),
            action_type=action_type,
            action_receipt_id=action_receipt_id,
        )


@dataclass(frozen=True, slots=True)
class ThreadWriteExpectation:
    """Exact durable state and authority a lifecycle writer observed."""

    status: ThreadStatus
    authority: RunWriteAuthority

    def __post_init__(self) -> None:
        """Refuse a partially typed election witness.

        These fields carry static types, but the checks defend against callers
        that construct this value from untrusted data and bypass the type
        checker entirely; `cast(object, ...)` only changes what the checker
        infers, not what runs.
        """
        if not isinstance(cast("object", self.status), ThreadStatus):
            raise TypeError("status must be a ThreadStatus")
        if not isinstance(cast("object", self.authority), RunWriteAuthority):
            raise TypeError("authority must be a RunWriteAuthority")
