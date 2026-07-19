"""Administrative shutdown requires attach AND the lifecycle capability."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest
from httpx import ASGITransport

from vaultspec_a2a.api.app import create_app
from vaultspec_a2a.api.dependencies import LIFECYCLE_CAPABILITY_HEADER

_ATTACH = "attach-credential-token-1122334455667788"
_CAPABILITY = "ownership-capability-token-99aabbccddeeff00"


def _make_app():
    """A real gateway app with both credential planes configured."""

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app = create_app(lifespan=_noop_lifespan)
    app.state.v1_service_token = _ATTACH
    app.state.lifecycle_capability = _CAPABILITY
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


async def _post_shutdown(headers: dict[str, str]) -> httpx.Response:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        return await client.post("/api/admin/shutdown", headers=headers)


@pytest.mark.asyncio
async def test_shutdown_requires_attach() -> None:
    """Without the attach credential the shutdown route is unauthenticated (401)."""
    response = await _post_shutdown({LIFECYCLE_CAPABILITY_HEADER: _CAPABILITY})
    assert response.status_code == 401
    assert _CAPABILITY not in response.text


@pytest.mark.asyncio
async def test_shutdown_requires_lifecycle_capability() -> None:
    """Attach alone is insufficient: the lifecycle capability is required (403)."""
    response = await _post_shutdown({"Authorization": f"Bearer {_ATTACH}"})
    assert response.status_code == 403
    assert _ATTACH not in response.text
    assert _CAPABILITY not in response.text


@pytest.mark.asyncio
async def test_shutdown_rejects_wrong_lifecycle_capability() -> None:
    """A wrong lifecycle capability with a valid attach is still forbidden (403)."""
    response = await _post_shutdown(
        {
            "Authorization": f"Bearer {_ATTACH}",
            LIFECYCLE_CAPABILITY_HEADER: "not-the-capability",
        }
    )
    assert response.status_code == 403
