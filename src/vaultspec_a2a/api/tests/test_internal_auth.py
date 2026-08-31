"""Gateway internal-route bearer auth through the real ``Depends()`` chain.

Closes the mutation-hole qa-gate found: the existing internal-route tests never set
a token or sent an Authorization header, so the gateway's match/mismatch/missing/
misconfigured cells only ran through the shared unit tests, not the wired
dependency. These exercise ``_verify_internal_token`` end to end on a live route.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ...testing import settings_override as _settings_override
from ...utils.enums import Environment
from ..internal import internal_router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(internal_router)
    return app


def test_internal_route_accepts_a_matching_bearer_token() -> None:
    with (
        _settings_override(
            environment=Environment.TESTING, internal_token="secret-token"
        ),
        TestClient(_app(), raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/internal/heartbeat",
            json={"active_threads": []},
            headers={"Authorization": "Bearer secret-token"},
        )
    assert resp.status_code == 200


def test_internal_route_rejects_a_mismatched_bearer_token() -> None:
    with (
        _settings_override(
            environment=Environment.TESTING, internal_token="secret-token"
        ),
        TestClient(_app(), raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/internal/heartbeat",
            json={"active_threads": []},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"
    # The gateway side does NOT set WWW-Authenticate (unlike the worker's 401).
    assert "www-authenticate" not in resp.headers


def test_internal_route_rejects_a_missing_authorization_header() -> None:
    with (
        _settings_override(
            environment=Environment.TESTING, internal_token="secret-token"
        ),
        TestClient(_app(), raise_server_exceptions=False) as client,
    ):
        resp = client.post("/internal/heartbeat", json={"active_threads": []})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"


def test_internal_route_500s_when_token_unset_outside_development() -> None:
    with (
        _settings_override(environment=Environment.TESTING, internal_token=None),
        TestClient(_app(), raise_server_exceptions=False) as client,
    ):
        resp = client.post("/internal/heartbeat", json={"active_threads": []})
    assert resp.status_code == 500
    assert "VAULTSPEC_INTERNAL_TOKEN required" in resp.json()["detail"]
