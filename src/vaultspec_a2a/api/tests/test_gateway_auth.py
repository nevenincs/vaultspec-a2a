"""Real FastAPI/HTTP coverage for the authenticated ``/v1`` boundary."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ...control.config import Settings
from ...utils import bearer_header
from .conftest import SEATED_ATTACH_TOKEN, make_app

_ROUTE_CLASSES: tuple[tuple[str, str, dict[str, Any], int], ...] = (
    (
        "POST",
        "/v1/runs",
        {"json": {"team_preset": "no-such-preset", "message": "start"}},
        422,
    ),
    ("GET", "/v1/runs", {}, 200),
    ("GET", "/v1/runs/no-such-run", {}, 404),
    ("GET", "/v1/runs/no-such-run/stream", {}, 404),
    ("POST", "/v1/runs/no-such-run/cancel", {}, 404),
    ("GET", "/v1/presets", {}, 200),
    ("GET", "/v1/service", {}, 200),
)


def _secured_app(session_factory: Any, checkpointer: Any) -> Any:
    """Build the real gateway fixture, presenting no credential of its own."""
    app, _aggregator, _worker, _checkpointer = make_app(
        session_factory, checkpointer, stamp_credentials=False
    )
    return app


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("route_case", _ROUTE_CLASSES)
async def test_every_v1_route_class_accepts_discovery_bearer(
    session_factory: Any,
    checkpointer: Any,
    route_case: tuple[str, str, dict[str, Any], int],
) -> None:
    method, path, kwargs, expected = route_case
    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers=bearer_header(SEATED_ATTACH_TOKEN),
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert response.status_code == expected, response.text


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("route_case", _ROUTE_CLASSES)
@pytest.mark.parametrize("headers", [{}, bearer_header("wrong-token")])
async def test_every_v1_route_class_rejects_missing_or_wrong_bearer(
    session_factory: Any,
    checkpointer: Any,
    route_case: tuple[str, str, dict[str, Any], int],
    headers: dict[str, str],
) -> None:
    method, path, kwargs, _expected = route_case
    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers=headers,
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid gateway service token"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("configured_token", [None, ""])
async def test_v1_fails_closed_without_configured_token_but_health_stays_public(
    session_factory: Any,
    checkpointer: Any,
    configured_token: str | None,
) -> None:
    app, _aggregator, _worker, _checkpointer = make_app(
        session_factory, checkpointer, stamp_credentials=False
    )
    app.state.v1_service_token = configured_token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        refused = await client.get("/v1/runs")
        health = await client.get("/health")

    assert refused.status_code == 503
    assert refused.json() == {"detail": "Gateway service token is not configured"}
    assert health.status_code == 200
    assert health.json()["service"] == "gateway"


def test_gateway_default_bind_is_loopback() -> None:
    assert Settings.model_fields["host"].default == "127.0.0.1"
