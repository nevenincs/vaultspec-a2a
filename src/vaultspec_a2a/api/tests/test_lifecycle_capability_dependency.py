"""Constant-time attach and lifecycle-capability dependencies over real HTTP."""

from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport

from ...api import auth, dependencies
from ...api.dependencies import (
    LIFECYCLE_CAPABILITY_HEADER,
    require_lifecycle_capability,
)
from ...api.routes import admin, gateway

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


def test_routes_mount_the_attach_gate_from_its_own_module() -> None:
    """Both gated surfaces mount the gate ``auth`` declares, not a copy of it.

    Read off the MOUNTED routers rather than off an import, because what protects
    a request is the callable FastAPI holds; a module could import the right
    function and still mount a different one. Compared by function identity, since
    a second implementation would carry the same name and the same signature.
    """
    versioned = [depends.dependency for depends in gateway.router.dependencies]
    assert auth.authenticate_request in versioned

    shutdown = next(
        route
        for route in admin.router.routes
        if isinstance(route, APIRoute) and route.path.endswith("/admin/shutdown")
    )
    mounted = [depends.dependency for depends in shutdown.dependencies]
    # The capability gate is layered ON TOP OF attach, never instead of it.
    assert auth.authenticate_request in mounted
    assert require_lifecycle_capability in mounted


def test_dependencies_offers_no_second_spelling_of_the_attach_gate() -> None:
    """``dependencies`` provides the capability gate; ``auth`` provides attach.

    The attach gate was once re-exported here as ``require_attach`` so routes had
    one import surface, which left the gate with two declared homes under two
    names - a reader searching either spelling found only half the story. Nothing
    here overrode or adapted it, so the alias bought a spelling and no behaviour.

    Checked by IDENTITY across the whole module, so re-introducing the alias under
    any other name fails too. An emptied module would satisfy that on its own, so
    the surface this module genuinely owns is pinned beside it.
    """
    aliases = [
        name
        for name in dir(dependencies)
        if getattr(dependencies, name) is auth.authenticate_request
    ]
    assert aliases == []
    assert "require_attach" not in dependencies.__all__

    assert "require_lifecycle_capability" in dependencies.__all__
    assert "LIFECYCLE_CAPABILITY_HEADER" in dependencies.__all__
    assert "get_aggregator" in dependencies.__all__


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
