"""Authentication for the engine-facing gateway surface."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request

__all__ = ["authenticate_request"]


async def authenticate_request(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Require the service-discovery bearer on an engine-facing request.

    The application snapshots the same configured token that it publishes in
    ``service.json``. Comparing encoded bytes with :func:`secrets.compare_digest`
    avoids data-dependent string comparison. A missing configured token is a
    service misconfiguration, not an authentication bypass; only an app created
    with the explicit test-only bypass may run without one.
    """
    expected = getattr(request.app.state, "v1_service_token", None)
    test_bypass = bool(
        getattr(request.app.state, "allow_unauthenticated_v1_for_testing", False)
    )
    if not isinstance(expected, str) or not expected:
        if test_bypass:
            return
        raise HTTPException(
            status_code=503,
            detail="Gateway service token is not configured",
        )

    supplied = (authorization or "").encode("utf-8")
    required = f"Bearer {expected}".encode()
    if not secrets.compare_digest(supplied, required):
        raise HTTPException(
            status_code=401,
            detail="Invalid gateway service token",
            headers={"WWW-Authenticate": "Bearer"},
        )
