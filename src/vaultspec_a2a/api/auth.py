"""API authentication module — ADR-009 §2.2 module hierarchy requirement.

Authentication is not yet implemented. This module provides the module
structure and stub function required by ADR-009. When authentication is
implemented, this module will provide request verification, token validation,
and principal extraction.

Future implementation will likely support:
- Bearer token validation (JWT or opaque tokens)
- API key authentication for local IDE clients
- Optional — the local-first design means auth may remain no-op for v1

See ADR-009 §2.2 for the module hierarchy mandate.
"""

from fastapi import Request


__all__ = ["authenticate_request"]


async def authenticate_request(request: Request) -> None:
    """Authenticate an incoming HTTP request.

    This is a no-op stub. When authentication is implemented, this function
    will validate Bearer tokens or API keys and raise ``HTTPException(401)``
    for unauthenticated requests.

    Usage (when wired)::

        from vaultspec_a2a.api.auth import authenticate_request
        from fastapi import Depends


        @router.get("/protected")
        async def endpoint(auth=Depends(authenticate_request)): ...
    """
    # TODO(vaultspec): implement authentication — validate Bearer token / API key
    # https://github.com/vaultspec/vaultspec-a2a/issues/1
    # For now this is a no-op; the API is intended for local use only.
    return
