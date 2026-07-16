"""Identifier validation and idempotency-key derivation.

The engine validates every id and token with one macro
(`authoring/model.rs`): non-empty after trim, at most 160 bytes, no
surrounding whitespace, ASCII alphanumeric plus ``_ - : . /`` only. This
module enforces the same rules client-side so malformed ids fail before a
round trip, and derives idempotency keys from stable run-local material so a
replay produces the byte-identical key the engine dedupes on.
"""

from __future__ import annotations

import hashlib
import re

__all__ = [
    "MAX_ID_BYTES",
    "derive_idempotency_key",
    "is_valid_id",
    "validate_id",
]

MAX_ID_BYTES = 160

# ASCII alphanumeric plus the four punctuation classes the engine macro allows.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:./]+$")


def is_valid_id(value: str) -> bool:
    """Return True when ``value`` satisfies the engine id grammar."""
    if not value or value != value.strip():
        return False
    if len(value.encode("utf-8")) > MAX_ID_BYTES:
        return False
    return bool(_ID_PATTERN.match(value))


def validate_id(value: str, *, field: str = "id") -> str:
    """Return ``value`` unchanged when valid, else raise ``ValueError``.

    Mirrors the engine's restricted-charset rule so a malformed id is rejected
    client-side rather than after a 400 round trip.
    """
    if not value or value != value.strip():
        raise ValueError(
            f"{field} must be non-empty and free of surrounding whitespace"
        )
    encoded = len(value.encode("utf-8"))
    if encoded > MAX_ID_BYTES:
        raise ValueError(f"{field} exceeds {MAX_ID_BYTES} bytes (got {encoded})")
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"{field} may contain only ASCII alphanumerics and the characters "
            f"_ - : . / (got {value!r})"
        )
    return value


def derive_idempotency_key(*material: str) -> str:
    """Derive a deterministic, engine-valid idempotency key from run-local parts.

    The key is stable across retries of the same logical command (same
    ``material``) so the engine's dedupe sees an identical key on replay, and
    it is confined to the id charset by construction (hex digest, colon
    separators). Callers pass stable run-local material such as the run id,
    command kind, and a per-command sequence — never wall-clock time or random
    bytes, which would defeat idempotent replay.
    """
    if not material or any(not part for part in material):
        raise ValueError("idempotency material must be one or more non-empty parts")
    digest = hashlib.sha256("\x1f".join(material).encode("utf-8")).hexdigest()
    return f"idk:{digest}"
