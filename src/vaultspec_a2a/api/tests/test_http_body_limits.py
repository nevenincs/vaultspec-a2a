"""Exercise body admission through the real gateway and worker factories."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import ValidationError

from ...control._worker_health import worker_liveness
from ...control.infra_config import InfraConfig
from ...streaming import RelayHub
from ...testing import settings_override
from ...utils import bearer_header
from ...worker.app import create_worker_app
from ..app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from fastapi import FastAPI

_TOKEN = "body-limit-test"
_AUTH = {**bearer_header(_TOKEN), "content-type": "application/json"}
_ROUTES = (
    "/internal/events/batch",
    "/internal/heartbeat",
    "/dispatch",
)


@asynccontextmanager
async def _no_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    yield


def _app(path: str) -> FastAPI:
    if path == "/dispatch":
        return create_worker_app(lifespan=_no_lifespan)
    app = create_app(lifespan=_no_lifespan)
    app.state.internal_token = _TOKEN
    app.state.relay_hub = RelayHub()
    app.state.db_session_factory = None
    return app


def _body(path: str, size: int) -> bytes:
    payload: dict[str, object]
    if path == "/internal/events/batch":
        payload = {"events": []}
    elif path == "/internal/heartbeat":
        payload = {"type": "heartbeat", "active_threads": ["t"]}
    else:
        payload = {"action": "cancel", "thread_id": "t"}
    encoded = json.dumps(payload).encode()
    assert len(encoded) <= size
    return encoded + b" " * (size - len(encoded))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _ROUTES)
@pytest.mark.parametrize(
    "framing",
    ["missing", "chunked", "underreported", "malformed", "negative", "duplicate"],
)
async def test_internal_streamed_body_cannot_bypass_limit(
    path: str, framing: str
) -> None:
    app = _app(path)
    liveness = worker_liveness(app.state)
    before = liveness.last_contact_ts
    cap = 1024 if path.endswith("/batch") else 256
    body = _body(path, cap + 1)
    consumed: list[int] = []

    async def chunks() -> AsyncIterator[bytes]:
        consumed.append(1)
        yield body[:128]
        consumed.append(2)
        yield body[128:]
        raise AssertionError("body limiter must stop at the overflowing chunk")

    headers = dict(_AUTH)
    if framing == "chunked":
        headers["transfer-encoding"] = "chunked"
    elif framing == "underreported":
        headers["content-length"] = "1"
    elif framing == "malformed":
        headers["content-length"] = "invalid"
    elif framing == "negative":
        headers["content-length"] = "-1"
    with settings_override(internal_token=_TOKEN, internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            request = client.build_request(
                method="POST", url=path, content=chunks(), headers=headers
            )
            if framing == "missing":
                request.headers.pop("transfer-encoding", None)
            elif framing == "duplicate":
                request.headers = httpx.Headers(
                    [
                        *request.headers.multi_items(),
                        ("content-length", "1"),
                        ("content-length", "2"),
                    ]
                )
            response = await client.send(request)

    assert response.status_code == 413
    assert consumed == [1, 2]
    assert liveness.last_contact_ts == before
    if path == "/dispatch":
        assert len(app.state.dispatch_ids) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _ROUTES)
async def test_internal_declared_oversize_does_not_read_body(path: str) -> None:
    cap = 1024 if path.endswith("/batch") else 256

    async def unread() -> AsyncIterator[bytes]:
        raise AssertionError("declared oversize must be rejected without receiving")
        yield b""

    with settings_override(internal_token=_TOKEN, internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app(path)), base_url="http://test"
        ) as client:
            response = await client.post(
                path,
                content=unread(),
                headers={**_AUTH, "content-length": str(cap + 1)},
            )
    assert response.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _ROUTES[:-1])
async def test_internal_exact_limit_body_is_accepted(path: str) -> None:
    cap = 1024 if path.endswith("/batch") else 256
    body = _body(path, cap)

    async def chunks() -> AsyncIterator[bytes]:
        yield body[:128]
        yield body[128:]

    app = _app(path)
    with settings_override(internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(path, content=chunks(), headers=_AUTH)
    assert response.status_code == 200
    if path.endswith("/heartbeat"):
        assert worker_liveness(app.state).active_threads == ["t"]


@pytest.mark.asyncio
async def test_dispatch_small_body_retains_authentication_and_validation() -> None:
    with settings_override(internal_token=_TOKEN, internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app("/dispatch")), base_url="http://test"
        ) as client:
            unauthorized = await client.post(
                "/dispatch", content=_body("/dispatch", 256)
            )
            invalid = await client.post("/dispatch", json={}, headers=_AUTH)
    assert unauthorized.status_code == 401
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_body_limit_counts_utf8_bytes() -> None:
    body = json.dumps({"active_threads": ["é" * 128]}, ensure_ascii=False).encode()
    assert len(body.decode()) < 256 < len(body)
    with settings_override(internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app("/internal/heartbeat")),
            base_url="http://test",
        ) as client:
            request = client.build_request(
                "POST", "/internal/heartbeat", content=body, headers=_AUTH
            )
            request.headers.pop("content-length", None)
            response = await client.send(request)
    assert response.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_all_gateway_write_methods_are_bounded(method: str) -> None:
    with settings_override(internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app("/internal/heartbeat")),
            base_url="http://test",
        ) as client:
            response = await client.request(method, "/unregistered", content=b"x" * 257)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_worker_body_limit_applies_before_authentication() -> None:
    with settings_override(internal_token=_TOKEN, internal_max_http_body_bytes=256):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app("/dispatch")), base_url="http://test"
        ) as client:
            response = await client.post("/dispatch", content=_body("/dispatch", 257))
    assert response.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("threads", [["t"] * 1025, ["t" * 129], "t", [1]])
async def test_heartbeat_schema_bounds_preserve_liveness_on_refusal(
    threads: object,
) -> None:
    app = _app("/internal/heartbeat")
    before = worker_liveness(app.state).last_contact_ts
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/heartbeat", json={"active_threads": threads}, headers=_AUTH
        )
    assert response.status_code == 422
    assert worker_liveness(app.state).last_contact_ts == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,size", [("thread_id", 129), ("dispatch_id", 129), ("content", 65537)]
)
async def test_dispatch_schema_rejects_oversized_fields(field: str, size: int) -> None:
    payload: dict[str, object] = {
        "action": "cancel",
        "thread_id": "t",
        "recursion_limit": 25,
    }
    payload[field] = "x" * size
    with settings_override(internal_token=_TOKEN):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app("/dispatch")), base_url="http://test"
        ) as client:
            response = await client.post("/dispatch", json=payload, headers=_AUTH)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field", ["internal_max_http_body_bytes", "internal_event_batch_body_multiplier"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_internal_body_limit_configuration_must_be_positive(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError, match=field):
        InfraConfig.model_validate({field: value})
