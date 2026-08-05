"""Authentication for the engine-facing gateway surface."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..utils.ipc_auth import BearerVerdict

__all__ = ["authenticate_request", "gateway_bearer_scheme", "verify_attach_bearer"]

#: Declares the bearer requirement in the generated OpenAPI document.
#:
#: This exists for the CONTRACT, not for verification: the comparison below reads
#: the raw header, because :func:`verify_attach_bearer` is shared with the desktop
#: health endpoint and must keep seeing the header exactly as sent. Without this
#: scheme the published document carried no ``securitySchemes`` entry and modeled
#: the credential as an optional free-text header, so a generated client came out
#: with no way to send it and the interactive docs offered no authorize control.
#:
#: ``auto_error=False`` is what keeps the declaration inert at runtime: FastAPI
#: emits the scheme and the per-operation ``security`` requirement from the
#: dependency graph, but raises nothing itself, leaving the 401/503 mapping in
#: :func:`authenticate_request` as the single place the verdict becomes a status.
gateway_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="GatewayServiceToken",
    description=(
        "Gateway service token. The service publishes it in an owner-restricted "
        "`service.token` handoff file adjacent to the `service.json` discovery "
        "record, whose `handoff_reference` names that file without embedding the "
        "secret. Send it as `Authorization: Bearer <token>`."
    ),
)


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
    authorization: str | None = Header(default=None, include_in_schema=False),
    _declared_scheme: Annotated[
        HTTPAuthorizationCredentials | None, Depends(gateway_bearer_scheme)
    ] = None,
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

    The two credential parameters are one credential read twice, for two different
    consumers. ``authorization`` is the raw header the verifier actually compares,
    kept out of the schema so the published contract does not also advertise it as
    a free-text parameter. ``_declared_scheme`` is never read: depending on
    :data:`gateway_bearer_scheme` is what puts the security requirement on every
    operation in the generated document. Deleting it would silently strip the
    contract's only auth affordance while leaving every request still authorized.
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
