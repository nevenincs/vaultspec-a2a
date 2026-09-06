"""Administrative shutdown requires attach AND the lifecycle capability."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from httpx import ASGITransport

from ...api.app import _bind_server_shutdown_owner, create_app
from ...api.dependencies import LIFECYCLE_CAPABILITY_HEADER
from ...api.routes.gateway import admission_gate
from ...control.drain import AdmissionState

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
        return await client.post("/admin/shutdown", headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, object()])
async def test_shutdown_refuses_missing_or_malformed_owner_before_admission_close(
    owner: object | None,
) -> None:
    app = _make_app()
    if owner is not None:
        app.state.request_server_shutdown = owner
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        response = await client.post(
            "/admin/shutdown",
            headers={
                "Authorization": f"Bearer {_ATTACH}",
                LIFECYCLE_CAPABILITY_HEADER: _CAPABILITY,
            },
        )

    assert response.status_code == 503
    admission = await admission_gate(app).admit("still-open-after-refusal")
    assert admission.admitted
    assert admission.state is AdmissionState.OPEN


@pytest.mark.asyncio
async def test_production_uvicorn_owner_returns_202_before_cooperative_exit() -> None:
    app = _make_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="error",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    _bind_server_shutdown_owner(app, server)
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started and server.servers:
                break
            await asyncio.sleep(0.01)
        assert server.started and server.servers, "Uvicorn owner did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                f"http://127.0.0.1:{port}/admin/shutdown",
                headers={
                    "Authorization": f"Bearer {_ATTACH}",
                    LIFECYCLE_CAPABILITY_HEADER: _CAPABILITY,
                },
            )
        assert response.status_code == 202
        assert not serving.done(), "server exited before the 202 reached the caller"
        await asyncio.wait_for(serving, timeout=2.0)
        assert server.should_exit
    finally:
        server.should_exit = True
        if not serving.done():
            await asyncio.wait_for(serving, timeout=2.0)


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


def test_the_stop_verb_addresses_the_path_the_gateway_actually_serves() -> None:
    """The CLI's stop path and the served route must be the same string.

    This binding is not pedantry. The two drifted: the CLI posted to
    ``/admin/shutdown`` while the gateway served the route only under the
    product prefix, so the authenticated drain answered 404 on every stop and
    the verb silently fell through to felling the process tree. The failure was
    invisible because a non-202 is indistinguishable from a refusal there.

    Asserting the CLI's own source rather than a copied constant is deliberate:
    a constant shared by both sides would move together and prove nothing.
    """
    import inspect
    import re

    from ...cli import service as service_verbs

    source = inspect.getsource(service_verbs.stop_service)
    posted = re.search(r'f"\{base_url\}(/[^"]*shutdown)"', source)
    assert posted is not None, "stop_service no longer posts a shutdown path"

    app = _make_app()
    served = {path for path in app.openapi()["paths"] if path.endswith("shutdown")}
    assert posted.group(1) in served, (posted.group(1), served)
