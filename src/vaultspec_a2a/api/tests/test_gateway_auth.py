"""Real FastAPI/HTTP coverage for the authenticated ``/v1`` boundary."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ...control.config import Settings
from .conftest import make_app

_SERVICE_TOKEN = "discovery-service-token"
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
    """Build the real gateway fixture and arm its production auth boundary."""
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.v1_service_token = _SERVICE_TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(("method", "path", "kwargs", "expected"), _ROUTE_CLASSES)
async def test_every_v1_route_class_accepts_discovery_bearer(
    session_factory: Any,
    checkpointer: Any,
    method: str,
    path: str,
    kwargs: dict[str, Any],
    expected: int,
) -> None:
    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert response.status_code == expected, response.text


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(("method", "path", "kwargs", "_expected"), _ROUTE_CLASSES)
@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token"])
async def test_every_v1_route_class_rejects_missing_or_wrong_bearer(
    session_factory: Any,
    checkpointer: Any,
    method: str,
    path: str,
    kwargs: dict[str, Any],
    _expected: int,
    authorization: str | None,
) -> None:
    app = _secured_app(session_factory, checkpointer)
    headers = {"Authorization": authorization} if authorization is not None else {}
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
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.v1_service_token = configured_token
    app.state.allow_unauthenticated_v1_for_testing = False
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


@pytest.mark.asyncio(loop_scope="function")
async def test_explicit_test_mode_is_the_only_tokenless_v1_bypass(
    session_factory: Any,
    checkpointer: Any,
) -> None:
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.v1_service_token = None
    assert app.state.allow_unauthenticated_v1_for_testing is True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.get("/v1/runs")

    assert response.status_code == 200


def test_gateway_default_bind_is_loopback() -> None:
    assert Settings.model_fields["host"].default == "127.0.0.1"
