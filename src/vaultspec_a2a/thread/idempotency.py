"""Pure idempotency-key policy — no I/O, no database.

Provides deterministic default idempotency keys for the run control actions a
client does not address itself, consolidating the hashlib patterns previously
inlined in service functions, and the bound every client-supplied key is held
to.

A derived default is only correct where repeating the same request means the
same act. It is wrong for a follow-up turn: two identical continuations are two
turns, and a content digest silently folds the second into the first, so that
verb takes the client's own key and has no default to fall back on.

Not every control action's key belongs here, and the exception is worth stating
so it is not "fixed" later. The clarification response derives a READABLE
prefixed key rather than a digest, because its restart-recovery sweep finds
unapplied actions by prefix-matching that key in SQL — a match no digest can
satisfy. That one lives beside its query, deliberately.
"""

from __future__ import annotations

import hashlib

__all__ = [
    "IDEMPOTENCY_KEY_MAX_LENGTH",
    "default_cancel_key",
    "default_permission_response_key",
]

IDEMPOTENCY_KEY_MAX_LENGTH = 255
"""Longest client-supplied idempotency key the gateway accepts.

The value is opaque to the gateway, so the only thing it can state about one is
how much of it will be stored and compared. Bounding it at the request edge
keeps an unbounded header out of a durable uniqueness constraint.
"""


def default_cancel_key(thread_id: str) -> str:
    """Derive a deterministic idempotency key for a cancel operation."""
    return hashlib.sha256(f"{thread_id}:cancel".encode()).hexdigest()


def default_permission_response_key(request_id: str, option_id: str) -> str:
    """Derive a deterministic idempotency key for a permission response.

    Keyed on the request AND the chosen option, so answering one request twice
    with the SAME option deduplicates while a genuine change of answer does not
    collide with the first.
    """
    return hashlib.sha256(f"{request_id}:{option_id}".encode()).hexdigest()
