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


def _app(internal_token: str | None) -> FastAPI:
    app = FastAPI()
    app.include_router(internal_router)
    app.state.internal_token = internal_token
    return app


def test_internal_route_accepts_a_matching_bearer_token() -> None:
    with (
        _settings_override(environment=Environment.TESTING),
        TestClient(_app("secret-token"), raise_server_exceptions=False) as client,
    ):
        resp = client.post(
            "/internal/heartbeat",
            json={"active_threads": []},
            headers={"Authorization": "Bearer secret-token"},
        )
    assert resp.status_code == 200


def test_internal_route_rejects_a_mismatched_bearer_token() -> None:
    with (
        _settings_override(environment=Environment.TESTING),
        TestClient(_app("secret-token"), raise_server_exceptions=False) as client,
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
        _settings_override(environment=Environment.TESTING),
        TestClient(_app("secret-token"), raise_server_exceptions=False) as client,
    ):
        resp = client.post("/internal/heartbeat", json={"active_threads": []})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid internal token"


def test_internal_route_500s_when_token_unset_outside_development() -> None:
    with (
        _settings_override(environment=Environment.TESTING),
        TestClient(_app(None), raise_server_exceptions=False) as client,
    ):
        resp = client.post("/internal/heartbeat", json={"active_threads": []})
    assert resp.status_code == 500
    assert "VAULTSPEC_A2A_INTERNAL_TOKEN required" in resp.json()["detail"]


def test_internal_route_refuses_an_app_that_seated_no_token_even_in_development() -> (
    None
):
    """A token left unseated is not an unconfigured token, so no bypass applies."""
    app = FastAPI()
    app.include_router(internal_router)
    with (
        _settings_override(environment=Environment.DEVELOPMENT),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        resp = client.post("/internal/heartbeat", json={"active_threads": []})
    assert resp.status_code == 500
