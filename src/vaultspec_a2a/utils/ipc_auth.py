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

import hmac
from enum import StrEnum

from .enums import Environment

__all__ = ["BearerVerdict", "verify_internal_bearer"]


class BearerVerdict(StrEnum):
    """The outcome of verifying an ``Authorization`` header against a credential.

    Shared by the gateway's bearer planes — the internal IPC below and the attach
    gate in :mod:`vaultspec_a2a.api.auth` — because the three outcomes are the
    same three whatever credential is being proven, and only the mapping onto a
    transport's error differs. A second enum with these members would be the
    duplication this vocabulary exists to prevent.
    """

    OK = "ok"  # authorized, or auth disabled in dev mode
    MISCONFIGURED = "misconfigured"  # token unset outside DEVELOPMENT
    UNAUTHORIZED = "unauthorized"  # header missing or not an exact Bearer match


def verify_internal_bearer(
    authorization: str | None,
    *,
    token: str | None,
    environment: Environment,
    environment_declared: bool = True,
) -> tuple[BearerVerdict, str]:
    """Verify an internal-IPC ``Authorization`` header against the configured *token*.

    Returns ``OK`` when the request is authorized, or when *token* is unset and a
    DECLARED development environment disables auth; ``MISCONFIGURED`` with an
    actionable detail when *token* is unset and the bypass does not apply;
    ``UNAUTHORIZED`` when the header is not exactly ``Bearer <token>``. The
    returned detail string is the message the caller raises to its client.

    *environment_declared* separates an operator who CHOSE development from a
    process that merely inherited it as the setting's default. Only the choice
    disables authentication. The distinction exists because the previous rule
    read a defaulted value as consent: a deployment that set no environment and
    no token served this surface unauthenticated, and the loud refusal that was
    supposed to protect it could only fire for an operator who had already
    configured the thing the refusal asks for. Fail-closed on omission puts the
    burden back where it belongs.
    """
    if token is None:
        if environment != Environment.DEVELOPMENT:
            return BearerVerdict.MISCONFIGURED, (
                f"VAULTSPEC_INTERNAL_TOKEN required in {environment.value} environment"
            )
        if not environment_declared:
            return BearerVerdict.MISCONFIGURED, (
                "VAULTSPEC_INTERNAL_TOKEN required: no environment was declared, "
                "so the development bypass does not apply. Set "
                "VAULTSPEC_ENVIRONMENT=development to run without an internal "
                "token, or supply the token."
            )
        return BearerVerdict.OK, ""
    # Constant-time compare so verifying the worker-IPC secret never leaks its
    # bytes through data-dependent timing; parity with the attach, lifecycle, and
    # WebSocket gates on the same credential planes.
    supplied = (authorization or "").encode("utf-8")
    if not hmac.compare_digest(supplied, f"Bearer {token}".encode()):
        return BearerVerdict.UNAUTHORIZED, "Invalid internal token"
    return BearerVerdict.OK, ""
