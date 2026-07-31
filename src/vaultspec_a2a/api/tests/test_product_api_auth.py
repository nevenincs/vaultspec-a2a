"""Dashboard product APIs require attach; minimal liveness stays ungated."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from ...api.app import create_app

_TOKEN = "attach-credential-token-fedcba9876543210"

# Representative product routes that must reject an unauthenticated caller. Each
# lives under the versioned router the register helper gates with attach.
_GATED_REQUESTS = (
    ("GET", "/v1/runs"),
    ("GET", "/v1/presets"),
)


def _make_gated_app():
    """A real gateway app with attach enforced and a known attach credential."""

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app = create_app(lifespan=_noop_lifespan)
    app.state.v1_service_token = _TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _GATED_REQUESTS)
async def test_product_routes_reject_unauthenticated(method: str, path: str) -> None:
    """A product API rejects a request with no attach credential."""
    app = _make_gated_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        response = await client.request(method, path)
    assert response.status_code == 401
    assert _TOKEN not in response.text


@pytest.mark.asyncio
async def test_minimal_liveness_is_ungated() -> None:
    """The top-level health probe answers an unauthenticated caller.

    The app under test has no runtime singletons seated, which is the shape of
    a gateway whose lifespan has not run or failed partway. The probe must still
    ANSWER: a 500 here reads to an external prober as "unreachable" rather than
    "unhealthy", hiding the very condition the probe exists to report. It
    reports degraded and names the missing runtime instead.
    """
    app = _make_gated_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded", body
    assert body["checks"]["gateway"]["status"] == "error", body
    assert "runtime not initialised" in body["checks"]["gateway"]["detail"], body
