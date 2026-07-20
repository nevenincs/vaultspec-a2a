"""The MCP adapter authenticates its gateway calls with the attach bearer.

A real in-process FastAPI gateway served over ``httpx.ASGITransport`` requires
``Authorization: Bearer <token>`` and records what it received. The adapter's
shared client is pointed at it exactly as production points at a real gateway;
no mock, no fake transport handler.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from httpx import ASGITransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from vaultspec_a2a.control.config import settings
from vaultspec_a2a.protocols.mcp import _http as mcp_http
from vaultspec_a2a.protocols.mcp._http import (
    _get_known_presets,
    _mcp_request,
    _reset_known_presets,
)

_TOKEN = "configured-service-token-1234567890abcdef"
_GATEWAY_URL = "http://127.0.0.1:18000"


def _gated_gateway() -> FastAPI:
    """A gateway whose /api surface requires the attach bearer."""
    app = FastAPI()
    app.state.seen = {"authorization": None}

    def _require_bearer(authorization: str | None) -> None:
        app.state.seen["authorization"] = authorization
        if authorization != f"Bearer {_TOKEN}":
            raise HTTPException(status_code=401, detail="missing or invalid bearer")

    @app.get("/api/teams")
    async def _teams(authorization: str | None = Header(default=None)) -> dict:
        _require_bearer(authorization)
        return {"presets": [{"id": "vaultspec-solo-coder"}]}

    @app.get("/api/threads/{thread_id}")
    async def _thread(
        thread_id: str, authorization: str | None = Header(default=None)
    ) -> dict:
        _require_bearer(authorization)
        return {"thread_id": thread_id, "status": "running"}

    return app


@asynccontextmanager
async def _adapter_client(app: FastAPI, *, token: str | None) -> AsyncIterator[FastAPI]:
    """Point the adapter's shared client at *app* with *token* configured.

    Saves and restores the process-global settings and shared client so the
    adapter talks to the in-process gated gateway for the body of the block.
    """
    originals = {
        "gateway_url": settings.gateway_url,
        "gateway_service_token": settings.gateway_service_token,
        "desktop_app_home": settings.desktop_app_home,
    }
    original_client = mcp_http._shared_client
    _reset_known_presets()
    settings.gateway_url = _GATEWAY_URL
    settings.gateway_service_token = token
    settings.desktop_app_home = None
    mcp_http._shared_client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url=_GATEWAY_URL,
    )
    try:
        yield app
    finally:
        client = mcp_http._shared_client
        mcp_http._shared_client = original_client
        for name, value in originals.items():
            setattr(settings, name, value)
        _reset_known_presets()
        if client is not None:
            await client.aclose()


@pytest.mark.asyncio
async def test_tool_request_sends_the_attach_bearer() -> None:
    """A configured token reaches the gated gateway as an Authorization header."""
    app = _gated_gateway()
    async with _adapter_client(app, token=_TOKEN):
        body = await _mcp_request("GET", "/api/threads/abc123", timeout=5.0)
        assert body == {"thread_id": "abc123", "status": "running"}
        assert app.state.seen["authorization"] == f"Bearer {_TOKEN}"


@pytest.mark.asyncio
async def test_preset_fetch_authenticates_against_the_gated_gateway() -> None:
    """Preset discovery reaches the gated gateway with the bearer and succeeds."""
    app = _gated_gateway()
    async with _adapter_client(app, token=_TOKEN):
        presets = await _get_known_presets()
        assert "vaultspec-solo-coder" in presets
        assert app.state.seen["authorization"] == f"Bearer {_TOKEN}"


@pytest.mark.asyncio
async def test_without_a_credential_the_gated_gateway_rejects() -> None:
    """No resolvable credential means no header, and the gate rejects the call.

    The regression guard: before the fix the adapter sent no bearer, so a gated
    gateway answered 401. With no configured token and an unarmed profile the
    adapter still sends none, and the request is refused - proving the header
    the fix adds is genuinely required.
    """
    app = _gated_gateway()
    async with _adapter_client(app, token=None):
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await _mcp_request("GET", "/api/threads/abc123", timeout=5.0)
        assert excinfo.value.response.status_code == 401
        assert app.state.seen["authorization"] is None
