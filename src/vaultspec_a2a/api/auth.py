"""Authentication for the engine-facing gateway surface."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request

from ..utils.ipc_auth import BearerVerdict

__all__ = ["authenticate_request", "verify_attach_bearer"]


def verify_attach_bearer(
    authorization: str | None, *, expected: object, test_bypass: bool
) -> BearerVerdict:
    """Verify an ``Authorization`` header against the gateway's attach credential.

    The one place the attach rule is stated, for every surface that gates on it.
    Two surfaces do: the engine-facing dependency below, which refuses a request
    outright, and the desktop health endpoint, which answers every caller but
    discloses the readiness projection only to a proven one. They are not two
    rules — they are two ERROR MAPPINGS of one verdict, so the rule is returned
    rather than raised and each caller maps it onto its own transport, exactly as
    :func:`~vaultspec_a2a.utils.ipc_auth.verify_internal_bearer` does for the
    worker plane.

    Stating it once is what keeps the two from drifting apart in the direction
    that matters. A disclosure gate that accepted anything the refusing gate
    rejects would hand an unauthenticated caller the readiness projection the
    refusing gate exists to protect, and nothing about either site would look
    wrong on its own — the drift is only visible by comparing them.

    ``expected`` is read from application state and so is typed as unknown: a
    gateway whose credential is missing or not a string is corrupted runtime
    state, reported as ``MISCONFIGURED`` rather than silently treated as an
    absent credential that anything could match. The test-only bypass is checked
    FIRST and short-circuits, because a test app is created without a credential
    and would otherwise be indistinguishable from that corruption.
    """
    if test_bypass:
        return BearerVerdict.OK
    if not isinstance(expected, str) or not expected:
        return BearerVerdict.MISCONFIGURED
    # Constant-time compare so verifying the attach credential never leaks its
    # bytes through data-dependent timing; parity with the internal-IPC and
    # lifecycle gates on the neighbouring credential planes.
    supplied = (authorization or "").encode("utf-8")
    if not hmac.compare_digest(supplied, f"Bearer {expected}".encode()):
        return BearerVerdict.UNAUTHORIZED
    return BearerVerdict.OK


async def authenticate_request(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Require the service-discovery bearer on an engine-facing request.

    The application snapshots either the explicitly configured gateway token or
    a generated per-process token. Lifecycle discovery publishes that bearer in
    an adjacent owner-restricted handoff file; ``service.json`` carries only its
    non-secret reference. The comparison itself belongs to
    :func:`verify_attach_bearer`; what stays here is this surface's mapping of
    the verdict — corrupted runtime state fails closed as a 503, a bad credential
    is a 401 carrying the ``WWW-Authenticate`` challenge, and only an app created
    with the explicit test-only bypass may run without a token.
    """
    verdict = verify_attach_bearer(
        authorization,
        expected=getattr(request.app.state, "v1_service_token", None),
        test_bypass=bool(
            getattr(request.app.state, "allow_unauthenticated_v1_for_testing", False)
        ),
    )
    if verdict is BearerVerdict.MISCONFIGURED:
        raise HTTPException(
            status_code=503,
            detail="Gateway service token is not configured",
        )
    if verdict is BearerVerdict.UNAUTHORIZED:
        raise HTTPException(
            status_code=401,
            detail="Invalid gateway service token",
            headers={"WWW-Authenticate": "Bearer"},
        )
