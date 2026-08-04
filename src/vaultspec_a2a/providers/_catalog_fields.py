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
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .provider_catalog import MAX_DISPLAY_LENGTH

if TYPE_CHECKING:
    from ._json_contract import JsonValue
    from ._stdio_rpc import ProtocolErrorFactory
    from .provider_catalog import ModelCatalogEntry, ProviderCatalogKey

__all__ = [
    "CatalogFieldReader",
    "display_label",
    "display_text",
    "local_id",
    "model_list_revision",
    "optional_description",
    "optional_text",
]

_MAX_FIELD_CHARS: Final = 1_024


def optional_text(value: JsonValue | None) -> str | None:
    """Return *value* when it is a non-blank string carrying no outer space."""
    return (
        value if isinstance(value, str) and value and value == value.strip() else None
    )


def display_label(text: str) -> str:
    """Bound a display name to what the catalog contract will accept.

    Truncation is the lane's posture and refusal is the model's: a provider
    shipping an over-long label, or a lane composing one out of parts that are
    each legal, must not cost the whole catalog. The bound is the model's to
    declare, because a lane cutting SHORTER silently shortens a name the model
    accepts, and one cutting LONGER hands over a value the model rejects.

    Trailing space is stripped afterwards because the model requires a bounded
    string AND an already-normalized one, and a cut landing on a space satisfies
    the first while breaking the second - a whole catalog lost to a bare
    ``ValueError`` from a dataclass constructor.
    """
    return text[:MAX_DISPLAY_LENGTH].rstrip()


def display_text(value: JsonValue | None, fallback: str) -> str:
    """Prefer the provider's display string, falling back to its raw value."""
    return display_label(optional_text(value) or fallback)


def optional_description(value: JsonValue | None) -> str | None:
    """Keep a provider description only when it is present and normalized."""
    text = optional_text(value)
    return None if text is None else text[:_MAX_FIELD_CHARS].rstrip()


def local_id(namespace: str, provider_value: str) -> str:
    """Derive this project's stable local identifier for a provider-issued value.

    Namespaced before hashing so two providers advertising the same model string
    do not collide, and separated by a NUL because that byte cannot occur in
    either part - concatenating them directly would let one namespace forge an
    identifier belonging to another.
    """
    encoded = f"{namespace}\0{provider_value}".encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def model_list_revision(
    key: ProviderCatalogKey, models: tuple[ModelCatalogEntry, ...]
) -> str:
    """Hash a catalog's provider-issued model values into a stable revision.

    Two lanes revision nothing but the bare ``provider_value`` list: the
    OpenAI-compatible HTTP surface, whose wire contract carries no native
    controls, and the in-process lane, which is computed rather than
    discovered and so has none either. The three RPC lanes (ACP, Codex,
    Kimi) advertise native controls and fold them into their own revision
    payload, which is why each keeps its own ``_revision`` instead of
    converging here - the shared shape ends where the payload does.
    """
    payload = {
        "provider_id": key.provider_id,
        "execution_mode": key.execution_mode,
        "models": [model.provider_value for model in models],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


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
