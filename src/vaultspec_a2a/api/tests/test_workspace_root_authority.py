"""Contract coverage for authenticated caller-selected workspace roots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ...control.config import settings
from .conftest import async_catalog_run_fields, make_app

if TYPE_CHECKING:
    from pathlib import Path

_TOKEN = "workspace-authority-token-0123456789abcdef"


def _secured_app(session_factory: Any, checkpointer: Any) -> Any:
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.v1_service_token = _TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    (
        (
            "POST",
            "/v1/runs",
            {
                "json": {
                    "team_preset": "mock-success-single",
                    "message": "start",
                    "metadata": {"workspace_root": "relative/workspace"},
                }
            },
        ),
        ("GET", "/v1/runs", {"params": {"workspace_root": "relative/workspace"}}),
        (
            "GET",
            "/v1/presets",
            {"params": {"workspace_root": "relative/workspace"}},
        ),
        (
            "GET",
            "/v1/provider-catalog",
            {"params": {"workspace_root": "relative/workspace"}},
        ),
    ),
)
async def test_every_workspace_bearing_route_authenticates_before_root_validation(
    session_factory: Any,
    checkpointer: Any,
    method: str,
    path: str,
    kwargs: dict[str, Any],
) -> None:
    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid gateway service token"}


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("route", ("/v1/runs", "/v1/presets"))
@pytest.mark.parametrize("invalid_kind", ("relative", "missing", "file"))
async def test_workspace_query_routes_refuse_invalid_roots(
    session_factory: Any,
    checkpointer: Any,
    tmp_path: Path,
    route: str,
    invalid_kind: str,
) -> None:
    workspace_file = tmp_path / "not-a-directory"
    workspace_file.write_text("not a workspace", encoding="utf-8")
    invalid = {
        "relative": "relative/workspace",
        "missing": str(tmp_path / "missing"),
        "file": str(workspace_file),
    }[invalid_kind]
    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as client:
        response = await client.get(route, params={"workspace_root": invalid})

    assert response.status_code == 422


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_caller_can_select_an_arbitrary_existing_root(
    session_factory: Any,
    checkpointer: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "user-selected-project"
    workspace.mkdir()
    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as client:
        catalog = await client.get(
            "/v1/provider-catalog", params={"workspace_root": str(workspace)}
        )
        presets = await client.get(
            "/v1/presets", params={"workspace_root": str(workspace)}
        )
        runs = await client.get("/v1/runs", params={"workspace_root": str(workspace)})
        fields = await async_catalog_run_fields(client, workspace_root=str(workspace))
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "arbitrary-workspace-authority",
                "team_preset": "mock-success-single",
                "message": "start",
                "metadata": {"workspace_root": str(workspace)},
                "selection": fields["selection"],
            },
        )

    assert catalog.status_code == 200, catalog.text
    assert presets.status_code == 200, presets.text
    assert runs.status_code == 200, runs.text
    assert start.status_code == 201, start.text


@pytest.mark.asyncio(loop_scope="function")
async def test_configured_unarmed_profile_confines_every_workspace_route(
    session_factory: Any,
    checkpointer: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed = tmp_path / "managed"
    workspace = managed / "project"
    foreign = tmp_path / "foreign"
    workspace.mkdir(parents=True)
    foreign.mkdir()
    monkeypatch.setattr(settings, "desktop_app_home", None)
    monkeypatch.setattr(settings, "workspace_root", managed)

    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as client:
        for route in ("/v1/provider-catalog", "/v1/presets", "/v1/runs"):
            admitted = await client.get(
                route, params={"workspace_root": str(workspace)}
            )
            refused = await client.get(route, params={"workspace_root": str(foreign)})
            ancestor = await client.get(route, params={"workspace_root": str(tmp_path)})
            assert admitted.status_code == 200, (route, admitted.text)
            assert refused.status_code == 422, (route, refused.text)
            assert ancestor.status_code == 422, (route, ancestor.text)

        fields = await async_catalog_run_fields(client, workspace_root=str(workspace))
        admitted_start = await client.post(
            "/v1/runs",
            json={
                "run_id": "managed-workspace-admitted",
                "team_preset": "mock-success-single",
                "message": "start",
                "metadata": {"workspace_root": str(workspace)},
                "selection": fields["selection"],
            },
        )
        refused_start = await client.post(
            "/v1/runs",
            json={
                "run_id": "managed-workspace-refused",
                "team_preset": "mock-success-single",
                "message": "start",
                "metadata": {"workspace_root": str(foreign)},
                "selection": fields["selection"],
            },
        )
        stage_refusals: list[httpx.Response] = []
        for label, refused_root in (("foreign", foreign), ("ancestor", tmp_path)):
            for stage in ("prepare", "commit"):
                stage_refusals.append(
                    await client.post(
                        "/v1/runs",
                        json={
                            "stage": stage,
                            "reservation_id": (
                                f"reserved-{label}-root" if stage == "commit" else None
                            ),
                            "run_id": f"managed-{stage}-{label}-refused",
                            "team_preset": "mock-success-single",
                            "message": "commit message" if stage == "commit" else "",
                            "metadata": {"workspace_root": str(refused_root)},
                            "selection": fields["selection"],
                        },
                    )
                )

    assert admitted_start.status_code == 201, admitted_start.text
    assert refused_start.status_code == 422, refused_start.text
    assert "configured workspace root" in refused_start.json()["detail"]
    for response in stage_refusals:
        assert response.status_code == 422, response.text
        assert "configured workspace root" in response.json()["detail"]


@pytest.mark.asyncio(loop_scope="function")
async def test_armed_desktop_preserves_arbitrary_existing_roots(
    session_factory: Any,
    checkpointer: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed = tmp_path / "managed"
    foreign = tmp_path / "foreign"
    desktop_home = tmp_path / "desktop-home"
    managed.mkdir()
    foreign.mkdir()
    desktop_home.mkdir()
    monkeypatch.setattr(settings, "desktop_app_home", desktop_home)
    monkeypatch.setattr(settings, "workspace_root", managed)

    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as client:
        response = await client.get(
            "/v1/provider-catalog", params={"workspace_root": str(foreign)}
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio(loop_scope="function")
async def test_configured_profile_refuses_symlink_escape(
    session_factory: Any,
    checkpointer: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed = tmp_path / "managed"
    foreign = tmp_path / "foreign"
    managed.mkdir()
    foreign.mkdir()
    escape = managed / "escape"
    escape.symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(settings, "desktop_app_home", None)
    monkeypatch.setattr(settings, "workspace_root", managed)

    app = _secured_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as client:
        fields = await async_catalog_run_fields(client, workspace_root=str(managed))
        response = await client.get(
            "/v1/provider-catalog", params={"workspace_root": str(escape)}
        )
        stage_responses = [
            await client.post(
                "/v1/runs",
                json={
                    "stage": stage,
                    "reservation_id": (
                        "reserved-symlink-root" if stage == "commit" else None
                    ),
                    "run_id": f"managed-{stage}-symlink-refused",
                    "team_preset": "mock-success-single",
                    "message": "commit message" if stage == "commit" else "",
                    "metadata": {"workspace_root": str(escape)},
                    "selection": fields["selection"],
                },
            )
            for stage in ("prepare", "commit")
        ]

    assert response.status_code == 422, response.text
    assert "configured workspace root" in response.json()["detail"]
    for stage_response in stage_responses:
        assert stage_response.status_code == 422, stage_response.text
        assert "configured workspace root" in stage_response.json()["detail"]
