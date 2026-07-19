"""Tests for worker app HTTP auth and health behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from ...control.config import settings
from ...ipc.schemas import DispatchRequest
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
    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    return create_worker_app(lifespan=_noop_lifespan)


def test_dispatch_rejects_missing_internal_token_outside_development() -> None:
    """Worker /dispatch should fail loudly when token auth is required but missing."""
    app = _make_app_without_lifespan()
    dispatch = DispatchRequest(
        action="cancel",
        thread_id="thread-1",
        recursion_limit=25,
    )
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
    dispatch = DispatchRequest(
        action="cancel",
        thread_id="thread-1",
        recursion_limit=25,
    )
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
    dispatch = DispatchRequest(
        action="cancel",
        thread_id="thread-1",
        recursion_limit=25,
    )
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


def test_admin_shutdown_rejects_missing_internal_token() -> None:
    """The eviction-path kill endpoint must not be callable without the token.

    A 401 is raised by the auth dependency BEFORE the handler runs, so the
    ``os.kill`` never fires - the endpoint is safe to probe here.
    """
    app = _make_app_without_lifespan()
    with (
        _SettingsOverride(
            environment=Environment.TESTING, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/admin/shutdown")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"


def test_admin_shutdown_rejects_invalid_internal_token() -> None:
    """The eviction-path kill endpoint must reject a wrong bearer token."""
    app = _make_app_without_lifespan()
    with (
        _SettingsOverride(
            environment=Environment.DEVELOPMENT, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/admin/shutdown",
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"


def test_health_rejects_missing_internal_token() -> None:
    """Worker /health requires the worker IPC credential when one is configured."""
    app = _make_app_without_lifespan()
    with (
        _SettingsOverride(
            environment=Environment.TESTING, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/health")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"


def test_health_rejects_invalid_internal_token() -> None:
    """Worker /health rejects a wrong worker IPC bearer."""
    app = _make_app_without_lifespan()
    with (
        _SettingsOverride(
            environment=Environment.DEVELOPMENT, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/health", headers={"Authorization": "Bearer wrong-token"})

    assert resp.status_code == 401


def test_health_accepts_valid_internal_token() -> None:
    """The paired gateway's bearer passes the worker /health gate."""
    app = _make_app_without_lifespan()
    with (
        _SettingsOverride(
            environment=Environment.DEVELOPMENT, internal_token="secret-token"
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.get(
            "/health", headers={"Authorization": "Bearer secret-token"}
        )

    assert resp.status_code == 200
    assert resp.json()["service"] == "worker"


def test_health_open_in_development_without_token() -> None:
    """A DEVELOPMENT worker with no token leaves /health open (bearer rule)."""
    app = _make_app_without_lifespan()
    with (
        _SettingsOverride(
            environment=Environment.DEVELOPMENT, internal_token=None
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/health")

    assert resp.status_code == 200
