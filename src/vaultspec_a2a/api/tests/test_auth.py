"""Tests for src/vaultspec_a2a/api/auth.py.

Verifies that authenticate_request is callable and async.
The function is intentionally a no-op per ADR-009 §2.2 — "stub until auth
provider is selected". These tests assert the contract that must hold when
a real implementation replaces the stub.
"""

import inspect

import pytest

from fastapi import Request

from ..auth import authenticate_request


class TestAuthenticateRequest:
    """Tests for the authenticate_request stub."""

    def test_is_callable(self) -> None:
        """authenticate_request is importable and callable."""
        assert callable(authenticate_request)

    def test_is_async(self) -> None:
        """authenticate_request is a coroutine function (async def)."""
        assert inspect.iscoroutinefunction(authenticate_request)

    @pytest.mark.asyncio
    async def test_returns_none_for_any_request(self) -> None:
        """authenticate_request returns None (no-op) for any request."""
        # Minimal scope that FastAPI Request accepts
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }

        async def receive():  # pragma: no cover
            return {"type": "http.disconnect"}

        async def send(msg):  # pragma: no cover
            pass

        request = Request(scope, receive, send)
        result = await authenticate_request(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_raise(self) -> None:
        """authenticate_request does not raise for any request (no-op stub)."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/threads",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer invalid-token")],
        }

        async def receive():  # pragma: no cover
            return {"type": "http.disconnect"}

        async def send(msg):  # pragma: no cover
            pass

        request = Request(scope, receive, send)
        # Must not raise — stub is unconditionally no-op
        await authenticate_request(request)
