"""Pure idempotency-key derivation — no I/O, no database.

Provides deterministic default idempotency keys for the run control actions,
consolidating the hashlib patterns previously inlined in service functions.

Not every control action's key belongs here, and the exception is worth stating
so it is not "fixed" later. The clarification response derives a READABLE
prefixed key rather than a digest, because its restart-recovery sweep finds
unapplied actions by prefix-matching that key in SQL — a match no digest can
satisfy. That one lives beside its query, deliberately.
"""

from __future__ import annotations

import hashlib

__all__ = [
    "default_cancel_key",
    "default_message_key",
    "default_permission_response_key",
]


def default_cancel_key(thread_id: str) -> str:
    """Derive a deterministic idempotency key for a cancel operation."""
    return hashlib.sha256(f"{thread_id}:cancel".encode()).hexdigest()


def default_message_key(thread_id: str, agent_id: str, content: str) -> str:
    """Derive a deterministic idempotency key for a follow-up message."""
    return hashlib.sha256(
        f"{thread_id}:message:{agent_id}:{content}".encode()
    ).hexdigest()


def default_permission_response_key(request_id: str, option_id: str) -> str:
    """Derive a deterministic idempotency key for a permission response.

    Keyed on the request AND the chosen option, so answering one request twice
    with the SAME option deduplicates while a genuine change of answer does not
    collide with the first.
    """
    return hashlib.sha256(f"{request_id}:{option_id}".encode()).hexdigest()
