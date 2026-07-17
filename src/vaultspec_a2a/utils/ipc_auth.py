"""Shared internal-IPC bearer-token verification (gateway <-> worker).

The single home for the bearer rule that both sides of the internal IPC enforce:
when the token is unset, auth is disabled in DEVELOPMENT but a hard
misconfiguration in every other environment; otherwise the ``Authorization`` header
must be exactly ``Bearer <token>``. Framework-free by design - the caller maps the
verdict onto its transport's error (an HTTP 500/401, a WebSocket close), so
per-caller nuances (the worker's ``WWW-Authenticate`` header, a WS close code) stay
with the caller while the rule itself lives in one place.
"""

from __future__ import annotations

from enum import StrEnum

from .enums import Environment

__all__ = ["BearerVerdict", "verify_internal_bearer"]


class BearerVerdict(StrEnum):
    """The outcome of verifying an internal-IPC ``Authorization`` header."""

    OK = "ok"  # authorized, or auth disabled in dev mode
    MISCONFIGURED = "misconfigured"  # token unset outside DEVELOPMENT
    UNAUTHORIZED = "unauthorized"  # header missing or not an exact Bearer match


def verify_internal_bearer(
    authorization: str | None, *, token: str | None, environment: Environment
) -> tuple[BearerVerdict, str]:
    """Verify an internal-IPC ``Authorization`` header against the configured *token*.

    Returns ``OK`` when the request is authorized (or *token* is unset and the
    environment is DEVELOPMENT, i.e. auth disabled); ``MISCONFIGURED`` with an
    actionable detail when *token* is unset outside DEVELOPMENT; ``UNAUTHORIZED``
    when the header is not exactly ``Bearer <token>``. The returned detail string is
    the message the caller raises to its client.
    """
    if token is None:
        if environment != Environment.DEVELOPMENT:
            return BearerVerdict.MISCONFIGURED, (
                f"VAULTSPEC_INTERNAL_TOKEN required in {environment.value} environment"
            )
        return BearerVerdict.OK, ""
    if authorization != f"Bearer {token}":
        return BearerVerdict.UNAUTHORIZED, "Invalid internal token"
    return BearerVerdict.OK, ""
