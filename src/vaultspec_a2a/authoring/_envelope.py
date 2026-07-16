"""Shared-envelope, tiers, and denial-as-value decoding.

The engine wraps every authoring response in a shared envelope: success is
``{data, tiers, next_cursor?}`` and a typed error is ``{error, error_kind?,
tiers}``. In-domain business denials are NOT errors — they are HTTP 200 values
carrying ``data.status = "denied"``, a snake_case ``data.denial_kind``
discriminator, and a human-readable ``data.eligibility.reason``. This module
models the request envelope and decodes responses into a success value or a
first-class :class:`Denial`, keyed on ``denial_kind``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from ._ids import validate_id

__all__ = [
    "AuthoringResponse",
    "CommandEnvelope",
    "Denial",
    "decode_success_envelope",
    "extract_denial",
]

# The engine tiers block is a nested, evolving structure; the client passes it
# through opaquely rather than over-fitting a schema that the engine owns.
Tiers = dict[str, Any]


class CommandEnvelope(BaseModel):
    """Request envelope wrapping every mutating authoring command.

    The idempotency key is a BODY field, never a header. ``api_version`` is a
    snake_case enum whose only variant is ``v1``.
    """

    api_version: Literal["v1"] = "v1"
    command: str
    idempotency_key: str
    payload: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, _context: object, /) -> None:
        """Validate the command kind and idempotency key against the id grammar."""
        validate_id(self.command, field="command")
        validate_id(self.idempotency_key, field="idempotency_key")

    def to_body(self) -> dict[str, Any]:
        """Serialize to the exact JSON body the engine extractor expects."""
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class AuthoringResponse:
    """A decoded success envelope: the ``data`` payload plus tiers and cursor."""

    data: Any
    tiers: Tiers
    next_cursor: str | None = None


@dataclass(frozen=True)
class Denial:
    """A decoded in-domain business denial (HTTP 200 value, not an error).

    ``denial_kind`` is the machine-readable snake_case discriminator (e.g.
    ``forbidden_actor``); ``reason`` is the human-readable eligibility reason.
    """

    denial_kind: str
    reason: str | None
    eligibility: dict[str, Any] | None
    tiers: Tiers


def extract_denial(body: dict[str, Any]) -> Denial | None:
    """Return a :class:`Denial` when ``body`` is a denial value, else None.

    A denial is a success-status (HTTP 200) envelope whose ``data.status`` is
    ``"denied"``; it is distinguished by value, not by transport status code.
    """
    data = body.get("data")
    if not isinstance(data, dict) or data.get("status") != "denied":
        return None
    eligibility = data.get("eligibility")
    # The reason lives at the DATA top level for an eligibility denial
    # (`denial_value` emits `{status, command, allowed, reason}` flat), and only
    # nested under `eligibility` for the shapes that carry a sub-object. Prefer the
    # top-level field so a flat eligibility denial's reason is not dropped to None
    # (which masked the real apply-conflict reason as an opaque "unknown: None").
    reason: str | None = None
    raw_reason = data.get("reason")
    if isinstance(raw_reason, str):
        reason = raw_reason
    elif isinstance(eligibility, dict):
        nested_reason = eligibility.get("reason")
        reason = nested_reason if isinstance(nested_reason, str) else None
    denial_kind = data.get("denial_kind")
    tiers = body.get("tiers")
    return Denial(
        denial_kind=str(denial_kind) if denial_kind is not None else "unknown",
        reason=reason,
        eligibility=eligibility if isinstance(eligibility, dict) else None,
        tiers=tiers if isinstance(tiers, dict) else {},
    )


def decode_success_envelope(body: dict[str, Any]) -> AuthoringResponse:
    """Decode a shared success envelope into an :class:`AuthoringResponse`."""
    next_cursor = body.get("next_cursor")
    tiers = body.get("tiers")
    return AuthoringResponse(
        data=body.get("data"),
        tiers=tiers if isinstance(tiers, dict) else {},
        next_cursor=next_cursor if isinstance(next_cursor, str) else None,
    )
