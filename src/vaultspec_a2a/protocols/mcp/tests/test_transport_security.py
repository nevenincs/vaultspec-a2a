"""DNS-rebinding protection on the MCP streamable-http transport.

No mocks: these mount the REAL Starlette app the ``--transport streamable-http``
entrypoint serves, wrapped in the REAL security middleware built from the REAL
settings object, and drive it over ``httpx.ASGITransport``. The assertions are
about what the middleware answers on the wire.

The SDK's middleware DISABLES the Host/Origin checks when it is handed no
settings, so the failure this guards against is silent: the server still works,
and only a rebinding attempt reveals that nothing was ever checked. That makes
the negative cases below the point of the file.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from ..__main__ import build_transport_security
from ..server import mcp

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# A tools/list body is enough to reach the transport: the security middleware
# runs before any MCP protocol handling, so a blocked request never gets far
# enough for the missing session to matter.
_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@asynccontextmanager
async def _serving_client() -> AsyncIterator[AsyncClient]:
    """Mount the real app with its real lifespan running.

    The Host/Origin checks live inside the streamable-http session manager,
    which refuses to handle a request until its task group is started by the
    app's lifespan. Driving the genuine lifespan context is what makes these
    requests traverse the same path a served request does.
    """
    app = mcp.streamable_http_app(transport_security=build_transport_security())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client,
    ):
        yield client


@pytest.mark.asyncio
async def test_rebinding_host_header_is_refused() -> None:
    """A Host the operator never allowed is refused before MCP handling."""
    async with _serving_client() as client:
        response = await client.post(
            "/mcp", json=_BODY, headers={**_HEADERS, "Host": "attacker.example"}
        )

    assert response.status_code == 421
    assert "Invalid Host header" in response.text


@pytest.mark.asyncio
async def test_browser_origin_rebinding_is_refused() -> None:
    """A cross-origin browser context cannot reach the loopback MCP server.

    The Host header is a legitimate one, so the refusal below can only come
    from the Origin check — the exact shape of a DNS-rebinding attempt, where
    the victim's browser sends a valid Host and an attacker-controlled Origin.
    """
    async with _serving_client() as client:
        response = await client.post(
            "/mcp",
            json=_BODY,
            headers={
                **_HEADERS,
                "Host": "127.0.0.1:8200",
                "Origin": "http://evil.example",
            },
        )

    assert response.status_code == 403
    assert "Invalid Origin header" in response.text


@pytest.mark.asyncio
async def test_loopback_client_passes_the_security_layer() -> None:
    """The ordinary local client is not blocked.

    A guard that refuses everything would satisfy the two tests above, so this
    pins the other side: a loopback Host with no Origin reaches MCP itself. The
    response is therefore an MCP-level answer, not one of the transport
    refusals — asserting only ``!= 421/403`` is what keeps this honest without
    re-testing protocol behaviour that belongs elsewhere.
    """
    async with _serving_client() as client:
        response = await client.post(
            "/mcp", json=_BODY, headers={**_HEADERS, "Host": "127.0.0.1:8200"}
        )

    assert response.status_code not in (421, 403)
    assert "Invalid Host header" not in response.text
    assert "Invalid Origin header" not in response.text


def test_configured_policy_is_loopback_only_by_default() -> None:
    """The shipped default must not admit a public hostname."""
    policy = build_transport_security()

    assert policy.enable_dns_rebinding_protection is True
    assert policy.allowed_hosts == ["localhost:*", "127.0.0.1:*"]
    assert policy.allowed_origins == ["http://localhost:*", "http://127.0.0.1:*"]
