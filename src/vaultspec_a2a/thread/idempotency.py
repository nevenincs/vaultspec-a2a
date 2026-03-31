"""Pure idempotency-key derivation — no I/O, no database.

Provides deterministic default idempotency keys for cancel and
message operations, consolidating the hashlib patterns previously
inlined in service functions.
"""

from __future__ import annotations

import hashlib


def default_cancel_key(thread_id: str) -> str:
    """Derive a deterministic idempotency key for a cancel operation."""
    return hashlib.sha256(f"{thread_id}:cancel".encode()).hexdigest()


def default_message_key(thread_id: str, agent_id: str, content: str) -> str:
    """Derive a deterministic idempotency key for a follow-up message."""
    return hashlib.sha256(
        f"{thread_id}:message:{agent_id}:{content}".encode()
    ).hexdigest()
