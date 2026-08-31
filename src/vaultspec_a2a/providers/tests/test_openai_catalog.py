"""Real-HTTP tests for authenticated OpenAI-compatible model discovery."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, override

import pytest

from ..openai_catalog import (
    OpenAICompatibleCatalogError,
    catalog_from_model_list,
    discover_openai_compatible_catalog,
)
from ..provider_catalog import (
    MAX_MODELS,
    AuthenticationState,
    CatalogStatus,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from .._json_contract import JsonObject, JsonValue

_KEY = ProviderCatalogKey("configured-provider", "openai-http")
_SECRET = "catalog-test-secret"


@dataclass(frozen=True, slots=True)
class _HttpResponse:
    status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    hold_open: bool = False


@dataclass(slots=True)
class _ServerState:
    responses: list[_HttpResponse]
    requests: list[tuple[str, str, str | None, str | None]] = field(
        default_factory=list
    )
    response_started: threading.Event = field(default_factory=threading.Event)
    connection_closed: threading.Event = field(default_factory=threading.Event)


def _handler(state: _ServerState) -> type[BaseHTTPRequestHandler]:
    class CatalogHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            state.requests.append(
                (
                    self.command,
                    self.path,
                    self.headers.get("Authorization"),
                    self.headers.get("Accept"),
                )
            )
            response = state.responses.pop(0)
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            content_length = len(response.body) + (100 if response.hold_open else 0)
            self.send_header("Content-Length", str(content_length))
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)
            self.wfile.flush()
            state.response_started.set()
            if response.hold_open:
                self.connection.settimeout(5.0)
                try:
                    while self.connection.recv(1):
                        pass
                except OSError:
                    pass
                finally:
                    state.connection_closed.set()

        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return CatalogHandler


@contextmanager
def _serve(*responses: _HttpResponse) -> Generator[tuple[str, _ServerState]]:
    state = _ServerState(list(responses))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    try:
        yield f"http://{host}:{port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _json_response(payload: JsonObject, *, status: int = 200) -> _HttpResponse:
    return _HttpResponse(status=status, body=json.dumps(payload).encode())


def _model_list(*identifiers: str) -> JsonObject:
    return {
        "object": "list",
        "data": [
            {
                "id": identifier,
                "object": "model",
                "created": 1_700_000_000,
                "owned_by": "provider-owner-that-is-not-served",
            }
            for identifier in identifiers
        ],
    }


def test_model_list_normalizes_only_provider_identifiers() -> None:
    catalog = catalog_from_model_list(
        _model_list("provider/model-b", "provider/model-a"),
        key=_KEY,
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert catalog.state.status is CatalogStatus.AVAILABLE
    assert [model.provider_value for model in catalog.models] == [
        "provider/model-a",
        "provider/model-b",
    ]
    assert catalog.native_controls == ()
    for model in catalog.models:
        assert model.display_name == model.provider_value
        assert model.description is None
        assert model.capabilities == ()
        assert model.native_control_ids == ()
    assert "provider-owner-that-is-not-served" not in repr(catalog)
    reordered = catalog_from_model_list(
        _model_list("provider/model-a", "provider/model-b"), key=_KEY
    )
    assert catalog.state.revision == reordered.state.revision


def test_empty_duplicate_oversized_and_paginated_lists_fail_closed() -> None:
    empty = catalog_from_model_list(_model_list(), key=_KEY)
    assert empty.state.status is CatalogStatus.UNAVAILABLE
    assert empty.state.reason == "provider returned no models"

    with pytest.raises(OpenAICompatibleCatalogError, match="duplicate identifiers"):
        catalog_from_model_list(_model_list("same", "same"), key=_KEY)

    with pytest.raises(
        OpenAICompatibleCatalogError, match=f"exceeds {MAX_MODELS} models"
    ):
        catalog_from_model_list(
            _model_list(
                *(f"provider/model-{index}" for index in range(MAX_MODELS + 1))
            ),
            key=_KEY,
        )

    paginated = _model_list("provider/model-a")
    paginated["has_more"] = True
    with pytest.raises(OpenAICompatibleCatalogError, match="cannot be exhausted"):
        catalog_from_model_list(paginated, key=_KEY)

    cursor_page = _model_list("provider/model-a")
    cursor_page["next_cursor"] = "credential-shaped-cursor"
    with pytest.raises(OpenAICompatibleCatalogError, match="cannot be exhausted"):
        catalog_from_model_list(cursor_page, key=_KEY)

    missing_list_type = _model_list("provider/model-a")
    missing_list_type.pop("object")
    with pytest.raises(OpenAICompatibleCatalogError, match="invalid object type"):
        catalog_from_model_list(missing_list_type, key=_KEY)

    missing_model_type = _model_list("provider/model-a")
    data = missing_model_type.get("data")
    assert isinstance(data, list)
    model = data[0]
    assert isinstance(model, dict)
    model.pop("object")
    with pytest.raises(OpenAICompatibleCatalogError, match="invalid object type"):
        catalog_from_model_list(missing_model_type, key=_KEY)


@pytest.mark.parametrize("created", [None, True, -1, 1.5, "1700000000"])
def test_documented_created_metadata_is_validated_before_discard(
    created: JsonValue,
) -> None:
    payload = _model_list("provider/model-a")
    data = payload.get("data")
    assert isinstance(data, list)
    model = data[0]
    assert isinstance(model, dict)
    model["created"] = created
    with pytest.raises(OpenAICompatibleCatalogError, match="created"):
        catalog_from_model_list(payload, key=_KEY)


@pytest.mark.parametrize("owned_by", [None, "", " owner", 42, "x" * 1_025])
def test_documented_owner_metadata_is_validated_before_discard(
    owned_by: JsonValue,
) -> None:
    payload = _model_list("provider/model-a")
    data = payload.get("data")
    assert isinstance(data, list)
    model = data[0]
    assert isinstance(model, dict)
    model["owned_by"] = owned_by
    with pytest.raises(OpenAICompatibleCatalogError, match="owned_by"):
        catalog_from_model_list(payload, key=_KEY)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.asyncio
async def test_non_finite_timeout_is_rejected_before_network(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        await discover_openai_compatible_catalog(
            base_url="http://127.0.0.1:9/v1",
            api_key=_SECRET,
            key=_KEY,
            timeout=timeout,
        )


@pytest.mark.asyncio
async def test_non_ascii_api_key_is_rejected_without_secret_disclosure() -> None:
    secret = "catalog-secret-ñ"
    with pytest.raises(ValueError) as raised:
        await discover_openai_compatible_catalog(
            base_url="http://127.0.0.1:9/v1",
            api_key=secret,
            key=_KEY,
        )

    assert str(raised.value) == "api_key must be a bounded normalized value"
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)
    assert secret not in repr(raised.value.__dict__)


@pytest.mark.asyncio
async def test_real_http_success_proves_auth_and_fixed_models_path() -> None:
    response = _json_response(_model_list("account/model-b", "account/model-a"))
    with _serve(response) as (base_url, state):
        discovery = await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert discovery.authentication is AuthenticationState.AUTHENTICATED
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE
    assert [model.provider_value for model in discovery.catalog.models] == [
        "account/model-a",
        "account/model-b",
    ]
    assert state.requests == [
        ("GET", "/v1/models", f"Bearer {_SECRET}", "application/json")
    ]
    assert _SECRET not in repr(discovery)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "authentication", "reason"),
    [
        (
            401,
            AuthenticationState.UNAUTHENTICATED,
            "provider model-list authentication failed",
        ),
        (
            403,
            AuthenticationState.UNKNOWN,
            "provider model-list request was forbidden",
        ),
    ],
)
async def test_real_http_auth_refusal_is_structured_and_redacted(
    status: int,
    authentication: AuthenticationState,
    reason: str,
) -> None:
    response = _HttpResponse(
        status=status,
        body=f'{{"error":"credential {_SECRET}"}}'.encode(),
    )
    with _serve(response) as (base_url, _):
        discovery = await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert discovery.authentication is authentication
    assert discovery.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert discovery.catalog.models == ()
    assert discovery.catalog.state.reason == reason
    assert _SECRET not in repr(discovery)


@pytest.mark.asyncio
async def test_real_http_provider_failure_is_static_and_does_not_follow_redirects() -> (
    None
):
    response = _HttpResponse(
        status=302,
        body=f'{{"error":"credential {_SECRET}"}}'.encode(),
        headers=(("Location", "https://credential-collector.invalid/models"),),
    )
    with (
        _serve(response) as (base_url, state),
        pytest.raises(OpenAICompatibleCatalogError) as raised,
    ):
        await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert str(raised.value) == "OpenAI-compatible model-list request failed"
    assert _SECRET not in str(raised.value)
    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_real_http_partial_content_cannot_become_a_selectable_catalog() -> None:
    response = _HttpResponse(
        status=206,
        body=json.dumps(_model_list("partial/model")).encode(),
        headers=(("Content-Range", "items 0-0/2"),),
    )
    with (
        _serve(response) as (base_url, state),
        pytest.raises(OpenAICompatibleCatalogError) as raised,
    ):
        await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert str(raised.value) == "OpenAI-compatible model-list request failed"
    assert "partial/model" not in str(raised.value)
    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_real_http_pagination_signal_refuses_partial_catalog() -> None:
    response = _HttpResponse(
        status=200,
        body=json.dumps(_model_list("account/model-a")).encode(),
        headers=(("Link", '</v1/models?after=a>; rel="prev next"'),),
    )
    with (
        _serve(response) as (base_url, state),
        pytest.raises(OpenAICompatibleCatalogError, match="cannot be exhausted"),
    ):
        await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_real_http_multi_value_next_link_refuses_partial_catalog() -> None:
    response = _HttpResponse(
        status=200,
        body=json.dumps(_model_list("account/model-a")).encode(),
        headers=(("Link", '</v1/models?after=a>; rel="next prev"'),),
    )
    with (
        _serve(response) as (base_url, state),
        pytest.raises(OpenAICompatibleCatalogError, match="cannot be exhausted"),
    ):
        await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert len(state.requests) == 1


@pytest.mark.asyncio
async def test_real_http_response_bound_is_enforced_without_diagnostic_leak() -> None:
    response = _HttpResponse(
        status=200,
        body=b"{" + _SECRET.encode() + b"x" * 1_048_576,
    )
    with (
        _serve(response) as (base_url, _),
        pytest.raises(OpenAICompatibleCatalogError) as raised,
    ):
        await discover_openai_compatible_catalog(
            base_url=base_url,
            api_key=_SECRET,
            key=_KEY,
        )

    assert str(raised.value) == (
        "OpenAI-compatible model-list response exceeds one MiB"
    )
    assert _SECRET not in str(raised.value)


@pytest.mark.asyncio
async def test_real_http_timeout_closes_the_network_connection() -> None:
    response = _HttpResponse(status=200, body=b"{", hold_open=True)
    with _serve(response) as (base_url, state):
        with pytest.raises(OpenAICompatibleCatalogError) as raised:
            await discover_openai_compatible_catalog(
                base_url=base_url,
                api_key=_SECRET,
                key=_KEY,
                timeout=0.1,
            )
        closed = await asyncio.to_thread(state.connection_closed.wait, 5.0)

    assert str(raised.value) == "OpenAI-compatible model-list request timed out"
    assert closed


@pytest.mark.asyncio
async def test_real_http_cancellation_closes_the_network_connection() -> None:
    response = _HttpResponse(status=200, body=b"{", hold_open=True)
    with _serve(response) as (base_url, state):
        task = asyncio.create_task(
            discover_openai_compatible_catalog(
                base_url=base_url,
                api_key=_SECRET,
                key=_KEY,
                timeout=10.0,
            )
        )
        started = await asyncio.to_thread(state.response_started.wait, 5.0)
        assert started
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        closed = await asyncio.to_thread(state.connection_closed.wait, 5.0)

    assert closed
