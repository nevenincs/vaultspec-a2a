"""Typed transport and identity failures for the authoring edge.

Transport and identity failures ARE typed HTTP errors (unlike in-domain
business denials, which are 200 values — see :mod:`._envelope`). The engine
distinguishes two 401 shapes: the OUTER machine ``bearer_gate`` returns a bare
``{"error": "Unauthorized"}`` with no ``error_kind``, while the INNER
per-actor layer returns ``authoring_actor_token_missing`` /
``authoring_actor_token_unknown`` WITH an ``error_kind``. This module models
that split so callers can tell "wrong machine bearer" from "wrong/missing
actor token" without guessing from the status code alone (both are 401).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AuthoringError",
    "AuthoringTransportError",
    "raise_for_typed_error",
]

# Inner actor-token rejection discriminators (carry an error_kind, status 401).
_ACTOR_TOKEN_ERROR_KINDS = frozenset(
    {"authoring_actor_token_missing", "authoring_actor_token_unknown"}
)


class AuthoringError(Exception):
    """Base class for all authoring-client failures."""


class AuthoringTransportError(AuthoringError):
    """A typed transport or identity failure returned by the engine.

    Carries the HTTP status, the engine ``error_kind`` discriminator when
    present, the human-readable ``error`` message, and the tiers block.
    """

    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        error_kind: str | None,
        tiers: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.error_kind = error_kind
        self.tiers = tiers or {}
        detail = f"{status_code}"
        if error_kind:
            detail += f" {error_kind}"
        super().__init__(f"authoring transport error ({detail}): {message}")

    @property
    def is_machine_bearer_rejection(self) -> bool:
        """True for the outer bearer-gate 401 (bare Unauthorized, no error_kind)."""
        return self.status_code == 401 and self.error_kind is None

    @property
    def is_actor_token_rejection(self) -> bool:
        """True for an inner per-actor 401 carrying an actor-token error_kind."""
        return self.status_code == 401 and self.error_kind in _ACTOR_TOKEN_ERROR_KINDS


def raise_for_typed_error(status_code: int, body: dict[str, Any]) -> None:
    """Raise :class:`AuthoringTransportError` when ``body`` is a typed error.

    A typed error carries a top-level ``error`` string; successful envelopes
    and 200-value denials carry ``data`` instead and pass through untouched.
    Any status at or above 400 is treated as an error even if the body is
    shapeless, so a transport failure never masquerades as success.
    """
    has_error = "error" in body
    if status_code < 400 and not has_error:
        return
    tiers = body.get("tiers")
    raise AuthoringTransportError(
        status_code=status_code,
        message=str(body["error"]) if has_error else "unknown authoring error",
        error_kind=(
            str(body["error_kind"]) if body.get("error_kind") is not None else None
        ),
        tiers=tiers if isinstance(tiers, dict) else {},
    )
