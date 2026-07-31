"""Attach is required on the versioned whitelist, and the surface is unchanged."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from ...api.app import create_app

_TOKEN = "attach-credential-token-0123456789abcdef"

# The versioned engine-facing surface: the six control verbs plus bounded
# active-run discovery, plus the droppable run-stream companion. Every entry is
# attach-gated; the set is fixed so an accidental new verb is caught.
#
# Permission-respond is the sixth verb and was added by an explicit decision
# amendment, not by drift - which is exactly what this set exists to force. The
# versioned stream already carries the permission REQUEST as an enumerated
# frame, so the surface could pose the question while only the transition
# surface could accept the answer; retiring that surface would have stranded
# every paused run. Anything appearing here without a matching amendment is the
# accident this guard is for.
_EXPECTED_V1_ROUTES = {
    "POST /v1/runs",
    "GET /v1/runs",
    "GET /v1/runs/{run_id}",
    "DELETE /v1/runs/{run_id}",
    "POST /v1/runs/{run_id}/archive",
    "POST /v1/runs/{run_id}/cancel",
    "POST /v1/runs/{run_id}/messages",
    "POST /v1/runs/{run_id}/permissions/{request_id}/respond",
    "GET /v1/runs/{run_id}/stream",
    "GET /v1/presets",
    "GET /v1/service",
    "GET /v1/team/status",
}

# The reviewed control whitelist that must reject an unauthenticated caller
# (run-stream shares the gate but is the SSE companion, not a control verb).
_WHITELIST_REQUESTS = (
    ("POST", "/v1/runs"),
    ("GET", "/v1/runs"),
    ("GET", "/v1/runs/some-run-id"),
    ("DELETE", "/v1/runs/some-run-id"),
    ("POST", "/v1/runs/some-run-id/cancel"),
    ("POST", "/v1/runs/some-run-id/messages"),
    ("POST", "/v1/runs/some-run-id/permissions/some-request-id/respond"),
    ("POST", "/v1/runs/some-run-id/archive"),
    ("GET", "/v1/presets"),
    ("GET", "/v1/service"),
    ("GET", "/v1/team/status"),
)


def _make_gated_app():
    """Create a real gateway app with attach enforced and a known credential."""

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app = create_app(lifespan=_noop_lifespan)
    app.state.v1_service_token = _TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


def test_v1_surface_is_not_expanded() -> None:
    """The versioned surface carries exactly the reviewed members, no more."""
    app = _make_gated_app()
    v1_routes = {
        f"{method.upper()} {path}"
        for path, operations in app.openapi().get("paths", {}).items()
        if path.startswith("/v1")
        for method in operations
    }
    assert v1_routes == _EXPECTED_V1_ROUTES


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _WHITELIST_REQUESTS)
async def test_whitelist_rejects_unauthenticated(method: str, path: str) -> None:
    """Every whitelist member rejects a request with no attach credential."""
    app = _make_gated_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        response = await client.request(method, path)
    assert response.status_code == 401
    assert _TOKEN not in response.text


@pytest.mark.asyncio
async def test_presets_admitted_with_attach_credential() -> None:
    """A correct attach bearer passes the gate through to the handler."""
    app = _make_gated_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        response = await client.get(
            "/v1/presets", headers={"Authorization": f"Bearer {_TOKEN}"}
        )
    assert response.status_code == 200
