"""Gateway-facing internal traffic accepts only the worker IPC credential."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from ...api.internal import internal_router
from ...testing import settings_override as _settings_override
from ...utils.enums import Environment

_WORKER_IPC = "worker-ipc-credential-0123456789abcdef"
_ATTACH = "attach-credential-abcdef0123456789ffff"


def _internal_app() -> FastAPI:
    app = FastAPI()
    app.include_router(internal_router)
    return app


async def _get_health(headers: dict[str, str]) -> httpx.Response:
    app = _internal_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://gateway.test"
    ) as client:
        return await client.get("/internal/health", headers=headers)


@pytest.mark.asyncio
async def test_internal_health_requires_worker_ipc() -> None:
    """The internal readiness probe rejects a request with no worker IPC bearer."""
    with _settings_override(
        environment=Environment.TESTING, internal_token=_WORKER_IPC
    ):
        response = await _get_health({})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_health_rejects_attach_credential() -> None:
    """The attach credential is not interchangeable with the worker IPC one."""
    with _settings_override(
        environment=Environment.TESTING, internal_token=_WORKER_IPC
    ):
        response = await _get_health({"Authorization": f"Bearer {_ATTACH}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_health_accepts_worker_ipc() -> None:
    """The worker IPC bearer passes the internal gate."""
    with _settings_override(
        environment=Environment.TESTING, internal_token=_WORKER_IPC
    ):
        response = await _get_health({"Authorization": f"Bearer {_WORKER_IPC}"})
    assert response.status_code == 200
    assert response.json()["service"] == "gateway"


@pytest.mark.asyncio
async def test_internal_heartbeat_rejects_attach_credential() -> None:
    """Event/heartbeat traffic likewise refuses the attach credential."""
    app = _internal_app()
    transport = ASGITransport(app=app)
    with _settings_override(
        environment=Environment.TESTING, internal_token=_WORKER_IPC
    ):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://gateway.test"
        ) as client:
            response = await client.post(
                "/internal/heartbeat",
                headers={"Authorization": f"Bearer {_ATTACH}"},
                json={"active_threads": []},
            )
    assert response.status_code == 401
