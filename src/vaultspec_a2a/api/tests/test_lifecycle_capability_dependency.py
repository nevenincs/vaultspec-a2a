"""Constant-time attach and lifecycle-capability dependencies over real HTTP."""

from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport

from vaultspec_a2a.api import auth
from vaultspec_a2a.api.dependencies import (
    LIFECYCLE_CAPABILITY_HEADER,
    require_attach,
    require_lifecycle_capability,
)

_CAPABILITY = "ownership-capability-token-abcdef0123456789"


def _app(*, capability: str | None, test_bypass: bool) -> FastAPI:
    """Build a minimal app exposing a lifecycle-gated route."""
    app = FastAPI()
    app.state.lifecycle_capability = capability
    app.state.allow_unauthenticated_v1_for_testing = test_bypass

    @app.post("/lifecycle", dependencies=[Depends(require_lifecycle_capability)])
    async def _lifecycle() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _post(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        return await client.post("/lifecycle", headers=headers or {})


def test_require_attach_is_the_shared_attach_gate() -> None:
    """The re-export is the one attach gate, not a second implementation."""
    assert require_attach is auth.authenticate_request


@pytest.mark.asyncio
async def test_correct_capability_admitted() -> None:
    """A matching capability header admits the lifecycle route."""
    app = _app(capability=_CAPABILITY, test_bypass=False)
    response = await _post(app, {LIFECYCLE_CAPABILITY_HEADER: _CAPABILITY})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_wrong_capability_forbidden_and_redacted() -> None:
    """A mismatched capability is a redacted 403 that leaks no expected value."""
    app = _app(capability=_CAPABILITY, test_bypass=False)
    response = await _post(app, {LIFECYCLE_CAPABILITY_HEADER: "wrong-capability-value"})
    assert response.status_code == 403
    assert _CAPABILITY not in response.text


@pytest.mark.asyncio
async def test_missing_capability_forbidden() -> None:
    """An absent capability header is forbidden."""
    app = _app(capability=_CAPABILITY, test_bypass=False)
    response = await _post(app)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unconfigured_capability_fails_closed() -> None:
    """Corrupted state with no runtime capability fails closed with 503."""
    app = _app(capability=None, test_bypass=False)
    response = await _post(app, {LIFECYCLE_CAPABILITY_HEADER: _CAPABILITY})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_test_bypass_admits_without_capability() -> None:
    """The explicit test-only bypass admits the route without a capability."""
    app = _app(capability=None, test_bypass=True)
    response = await _post(app)
    assert response.status_code == 200
