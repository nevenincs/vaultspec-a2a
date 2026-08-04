"""The field-level normalization every catalog lane performs, declared once.

Four discovery lanes - ACP, Codex, Kimi, and the OpenAI-compatible HTTP surface -
read provider-controlled JSON and reduce it to the catalog contract. Each grew
the same primitives independently, differing only in DIALECT: which typed error
they raise and which provider name prefixes it. The mechanism, the bounds, and
the order of the guards were identical.

The dialect stays a caller-side argument, matching the convention the stdio
reader established: a lane passes an error factory that builds its own typed
error, because a Kimi caller reading a Codex-shaped refusal would be told
something untrue about which provider returned the bad field. Only the strict
reader needs that factory, so it is the only member bound to a lane; the rest
are pure and shared as free functions.

The split between the strict and lenient readers is a real contract difference
rather than an accident of naming, which is why one module is not enough to hold
both under one name. A REQUIRED field is structural - its absence means the
payload is not the shape the lane believes it is, so discovery refuses. An
OPTIONAL field is decoration, and a provider that omits it must not lose the
whole catalog.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ._json_contract import JsonValue
    from ._stdio_rpc import ProtocolErrorFactory

__all__ = [
    "CatalogFieldReader",
    "display_text",
    "local_id",
    "optional_description",
    "optional_text",
]

_MAX_FIELD_CHARS: Final = 1_024
_MAX_DISPLAY_CHARS: Final = 256


def optional_text(value: JsonValue | None) -> str | None:
    """Return *value* when it is a non-blank string carrying no outer space."""
    return (
        value if isinstance(value, str) and value and value == value.strip() else None
    )


def display_text(value: JsonValue | None, fallback: str) -> str:
    """Prefer the provider's display string, falling back to its raw value."""
    return (optional_text(value) or fallback)[:_MAX_DISPLAY_CHARS]


def optional_description(value: JsonValue | None) -> str | None:
    """Keep a provider description only when it is present and normalized."""
    text = optional_text(value)
    return None if text is None else text[:_MAX_FIELD_CHARS]


def local_id(namespace: str, provider_value: str) -> str:
    """Derive this project's stable local identifier for a provider-issued value.

    Namespaced before hashing so two providers advertising the same model string
    do not collide, and separated by a NUL because that byte cannot occur in
    either part - concatenating them directly would let one namespace forge an
    identifier belonging to another.
    """
    encoded = f"{namespace}\0{provider_value}".encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class CatalogFieldReader:
    """Reads structurally required fields, refusing in one lane's dialect."""

    protocol_error: ProtocolErrorFactory

    def required_text(self, value: JsonValue | None, *, field: str) -> str:
        """Return *value* as a bounded normalized string, or refuse."""
        text = optional_text(value)
        if text is None:
            raise self.protocol_error(
                f"catalog field {field!r} must be a normalized non-blank string"
            )
        if len(text) > _MAX_FIELD_CHARS:
            raise self.protocol_error(
                f"catalog field {field!r} exceeds 1024 characters"
            )
        return text
