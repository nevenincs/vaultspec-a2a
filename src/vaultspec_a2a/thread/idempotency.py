"""Pure idempotency-key policy — no I/O, no database.

Every journal key the gateway derives rather than takes from a client is built
here, so the writer that stores a row and the reader that looks it up by key
can never spell it two ways. Keys are compared as stored, so no builder may
change a value it has already produced. The bound every client-supplied key is
held to lives here too.

Two shapes exist, and the difference is a requirement rather than drift.

A run control action a client does not address itself gets a deterministic
digest default. A derived default is only correct where repeating the same
request means the same act. It is wrong for a follow-up turn: two identical
continuations are two turns, and a content digest silently folds the second
into the first, so that verb takes the client's own key and has no default to
fall back on.

Every other derived key is a READABLE ``<prefix>:<identity>`` string, which is
what lets a reader find rows by prefix: a SQL ``LIKE`` takes the exported prefix,
and a settlement owner that has to tell one resume from another takes the typed
:class:`ResumeIntent` this module reads the prefix into, rather than matching a
prefix of its own. A digest has no queryable prefix, so converging those keys
onto the digest shape would make the reader match nothing, and nothing would
raise.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from .action_receipts import sha256_hex

__all__ = [
    "CLARIFICATION_RESPONSE_KEY_PREFIX",
    "IDEMPOTENCY_KEY_MAX_LENGTH",
    "ResumeIntent",
    "authoring_verdict_action_key",
    "clarification_response_action_key",
    "default_cancel_key",
    "default_permission_response_key",
    "permission_duplicate_action_key",
    "permission_rejection_action_key",
    "permission_request_action_key",
    "permission_response_action_key",
    "permission_response_applied_action_key",
    "resume_intent",
    "thread_create_action_key",
]

IDEMPOTENCY_KEY_MAX_LENGTH = 255
"""Longest client-supplied idempotency key the gateway accepts.

The value is opaque to the gateway, so the only thing it can state about one is
how much of it will be stored and compared. Bounding it at the request edge
keeps an unbounded header out of a durable uniqueness constraint.
"""

CLARIFICATION_RESPONSE_KEY_PREFIX = "clarification-response:"
"""Prefix the clarification restart-recovery sweep matches unapplied rows by."""

_AUTHORING_VERDICT_KEY_PREFIX = "authoring-verdict:"
"""Prefix that tells a verdict resume from the other resumes on its wire verb.

Private: no query matches it, and the one reader that has to recognise it reads
it through :func:`resume_intent`.
"""


class ResumeIntent(StrEnum):
    """What one accepted ``resume`` answers, as its journal key records it.

    Unrelated answers share the ``resume`` wire verb and the ``RESUME`` control
    action, and each has a settlement owner of its own. The readable journal key
    is the only durable record of which answer a row holds, so it is read into a
    typed member exactly once, here, rather than re-derived from a string prefix
    by every owner that has to tell them apart.
    """

    CLARIFICATION = "clarification"
    AUTHORING_VERDICT = "authoring_verdict"


_RESUME_INTENTS: Final[tuple[tuple[str, ResumeIntent], ...]] = (
    (CLARIFICATION_RESPONSE_KEY_PREFIX, ResumeIntent.CLARIFICATION),
    (_AUTHORING_VERDICT_KEY_PREFIX, ResumeIntent.AUTHORING_VERDICT),
)


def resume_intent(idempotency_key: str) -> ResumeIntent | None:
    """Return what a resume's journal key says it answers, or ``None``.

    ``None`` means the key belongs to no resume this policy knows: the row is
    not one of the answers above, so no settlement owner may claim it.
    """
    for prefix, intent in _RESUME_INTENTS:
        if idempotency_key.startswith(prefix):
            return intent
    return None


def default_cancel_key(thread_id: str) -> str:
    """Derive a deterministic idempotency key for a cancel operation."""
    return sha256_hex(f"{thread_id}:cancel".encode())


def default_permission_response_key(request_id: str, option_id: str) -> str:
    """Derive a deterministic idempotency key for a permission response.

    Keyed on the request AND the chosen option, so answering one request twice
    with the SAME option deduplicates while a genuine change of answer does not
    collide with the first.
    """
    return sha256_hex(f"{request_id}:{option_id}".encode())


def thread_create_action_key(thread_id: str) -> str:
    """Return the key of a run's initial ingest, which holds its graph program."""
    return f"thread-create:{thread_id}"


def clarification_response_action_key(request_id: str) -> str:
    """Return the key of a clarification resolution, as a READABLE prefix.

    The recovery sweep finds every unapplied clarification action by matching
    :data:`CLARIFICATION_RESPONSE_KEY_PREFIX` in SQL, so this key must keep
    that prefix and must never become a digest. Any change here has to move
    the recovery query with it.
    """
    return f"{CLARIFICATION_RESPONSE_KEY_PREFIX}{request_id}"


def permission_request_action_key(request_id: str) -> str:
    """Return the key of the journal row recording a parked permission request."""
    return f"permission-request:{request_id}"


def permission_response_action_key(request_id: str) -> str:
    """Return the single journal identity shared by every client retry."""
    return f"permission-response:{request_id}"


def permission_rejection_action_key(idempotency_key: str) -> str:
    """Return the key recording a refused response under the client's key."""
    return f"permission-rejection:{idempotency_key}"


def permission_duplicate_action_key(idempotency_key: str) -> str:
    """Return the key recording a response to an already-applied request."""
    return f"permission-duplicate:{idempotency_key}"


def permission_response_applied_action_key(request_id: str) -> str:
    """Return the key recording that the worker applied a permission response."""
    return f"permission-response-applied:{request_id}"


def authoring_verdict_action_key(proposal_id: str) -> str:
    """Return the request-level journal key for one document-gate verdict."""
    return f"{_AUTHORING_VERDICT_KEY_PREFIX}{proposal_id}"
