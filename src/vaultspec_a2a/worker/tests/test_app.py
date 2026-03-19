"""Tests for worker app HTTP auth and health behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from ...api.schemas.internal import DispatchRequest
from ...core.config import settings
from ...utils.enums import Environment
from ..app import create_worker_app


class _SettingsOverride:
    """Temporarily override settings attributes for a test."""

    def __init__(self, **updates: object) -> None:
        self._updates = updates
        self._originals: dict[str, object] = {}

    def __enter__(self) -> None:
        for name, value in self._updates.items():
            self._originals[name] = getattr(settings, name)
            setattr(settings, name, value)

    def __exit__(self, *_args: object) -> None:
        for name, value in self._originals.items():
            setattr(settings, name, value)


def _make_app_without_lifespan():
    app = create_worker_app()

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.router.lifespan_context = _noop_lifespan
    return app


def test_dispatch_rejects_missing_internal_token_outside_development() -> None:
    """Worker /dispatch should fail loudly when token auth is required but missing."""
    app = _make_app_without_lifespan()
    dispatch = DispatchRequest(action="cancel", thread_id="thread-1")
    with (
        _SettingsOverride(
            environment=Environment.TESTING, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/dispatch", json=dispatch.model_dump())

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"


def test_dispatch_rejects_missing_token_configuration_outside_development() -> None:
    """Worker /dispatch should fail loudly when internal auth is not configured."""
    app = _make_app_without_lifespan()
    dispatch = DispatchRequest(action="cancel", thread_id="thread-1")
    with (
        _SettingsOverride(
            environment=Environment.TESTING,
            internal_token=None,
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/dispatch", json=dispatch.model_dump())

    assert resp.status_code == 500
    assert "VAULTSPEC_INTERNAL_TOKEN required" in resp.json()["detail"]


def test_dispatch_rejects_invalid_internal_token() -> None:
    """Worker /dispatch should reject incorrect bearer tokens."""
    app = _make_app_without_lifespan()
    dispatch = DispatchRequest(action="cancel", thread_id="thread-1")
    with (
        _SettingsOverride(
            environment=Environment.DEVELOPMENT, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/dispatch",
            json=dispatch.model_dump(),
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"
