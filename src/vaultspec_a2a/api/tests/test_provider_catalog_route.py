"""Real-behavior coverage for the versioned provider-catalog producer."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from httpx import ASGITransport
from pydantic import ValidationError

from ...api.app import create_app
from ...api.schemas.provider_catalog import ProviderCatalogResponse
from ...database.thread_repository import normalize_workspace_identity
from ...providers.lane_admission import is_catalog_lane_admissible
from ...providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ControlKind,
    HealthState,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderRecord,
    StructuredProviderHealth,
)
from ...providers.provider_catalog_service import (
    PROVIDER_CATALOG_CACHE_TTL,
    ProviderCatalogScopeCapacityError,
    ProviderCatalogService,
    validate_public_catalog_bounds,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

_TOKEN = "provider-catalog-attach-token-0123456789"


def _gated_app() -> FastAPI:
    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI):
        yield

    app = create_app(lifespan=_noop_lifespan)
    app.state.v1_service_token = _TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_kind", ["relative", "missing", "file"])
async def test_route_rejects_workspace_before_discovery(
    tmp_path: Path, invalid_kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = workspace / "not-a-directory.txt"
    file_path.write_text("not a workspace", encoding="utf-8")
    invalid = {
        "relative": "relative/workspace",
        "missing": str(tmp_path / "missing"),
        "file": str(file_path),
    }[invalid_kind]
    app = _gated_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://desktop.test"
    ) as client:
        response = await client.get(
            "/v1/provider-catalog",
            params={"workspace_root": invalid},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
    assert response.status_code == 422
    assert getattr(app.state, "provider_catalog_service", None) is None


@pytest.mark.asyncio
async def test_route_rejects_refresh_and_duplicate_workspace_queries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = _gated_app()
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://desktop.test"
    ) as client:
        refresh = await client.get(
            "/v1/provider-catalog",
            params={"workspace_root": str(workspace), "refresh": "true"},
            headers=headers,
        )
        duplicate = await client.get(
            "/v1/provider-catalog",
            params=[
                ("workspace_root", str(workspace)),
                ("workspace_root", str(workspace)),
            ],
            headers=headers,
        )
    assert refresh.status_code == 422
    assert duplicate.status_code == 422
    assert getattr(app.state, "provider_catalog_service", None) is None


@pytest.mark.asyncio
async def test_authenticated_route_serves_all_registered_lanes_in_order(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = _gated_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://desktop.test",
        timeout=30,
    ) as client:
        response = await client.get(
            "/v1/provider-catalog",
            params={"workspace_root": str(workspace)},
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["api_version"] == "v1"
    assert [record["provider_id"] for record in body["providers"]] == [
        "antigravity",
        "claude",
        "codex",
        "gemini",
        "kimi",
        "openai",
        "zai",
        "zhipu",
    ]
    assert all(record["catalog"]["schema_version"] == 1 for record in body["providers"])
    assert all("provider_value" not in str(record) for record in body["providers"])
    assert body["providers"][5]["catalog"]["state"]["status"] == "unavailable"
    assert body["providers"][6]["catalog"]["state"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_canonical_aliases_share_one_bounded_workspace_scope(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    canonical = normalize_workspace_identity(workspace)
    alias = normalize_workspace_identity(workspace / ".." / workspace.name)
    assert alias == canonical

    service = ProviderCatalogService(max_workspace_scopes=2)
    first, second = await asyncio.gather(
        service._acquire_scope(canonical), service._acquire_scope(alias)
    )
    assert first is second
    assert len(service._scopes) == 1
    await asyncio.gather(service._release_scope(first), service._release_scope(second))


@pytest.mark.asyncio
async def test_concurrent_workspace_churn_stays_within_scope_capacity(
    tmp_path: Path,
) -> None:
    roots: list[str] = []
    for index in range(8):
        root = tmp_path / f"workspace-{index}"
        root.mkdir()
        roots.append(normalize_workspace_identity(root))
    service = ProviderCatalogService(max_workspace_scopes=3)
    acquired = await asyncio.gather(
        *(service._acquire_scope(root) for root in roots), return_exceptions=True
    )
    scopes = [item for item in acquired if not isinstance(item, BaseException)]
    refused = [item for item in acquired if isinstance(item, BaseException)]
    assert len(scopes) == 3
    assert len(refused) == 5
    assert all(isinstance(item, ProviderCatalogScopeCapacityError) for item in refused)
    assert len(service._scopes) == 3
    await asyncio.gather(*(service._release_scope(scope) for scope in scopes))


def test_exact_lane_admission_does_not_inherit_from_same_provider() -> None:
    assert is_catalog_lane_admissible(ProviderCatalogKey("codex", "codex-app-server"))
    assert not is_catalog_lane_admissible(
        ProviderCatalogKey("claude", "claude-agent-acp:node")
    )


def test_cache_ttl_is_named_positive_and_bounded() -> None:
    assert timedelta(seconds=1) <= PROVIDER_CATALOG_CACHE_TTL <= timedelta(hours=1)


def test_overlong_public_identifier_is_rejected_per_catalog_lane() -> None:
    now = datetime.now(UTC)
    catalog = ProviderCatalog(
        key=ProviderCatalogKey("codex", "codex-app-server"),
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision="r" * 513,
            expires_at=now + timedelta(minutes=1),
        ),
        models=(),
    )
    with pytest.raises(ValueError, match="invalid public identifier"):
        validate_public_catalog_bounds(catalog)
    with pytest.raises(ValidationError):
        ProviderCatalogResponse.model_validate(
            {
                "api_version": "v1",
                "providers": [
                    {
                        "provider_id": "codex",
                        "display_name": "Codex",
                        "execution_mode": "codex-app-server",
                        "health": {
                            "configured": "unknown",
                            "transport": "unknown",
                            "authentication": "unknown",
                            "catalog": "available",
                            "admission": "admitted",
                            "selectable": False,
                            "reasons": [],
                            "checked_at": now,
                        },
                        "catalog": {
                            "schema_version": 1,
                            "state": {
                                "status": "available",
                                "checked_at": now,
                                "revision": "r" * 513,
                                "expires_at": now + timedelta(minutes=1),
                            },
                            "models": [],
                            "native_controls": [],
                        },
                    }
                ],
            }
        )
    assert not is_catalog_lane_admissible(
        ProviderCatalogKey("claude", "claude-agent-acp:future-transport")
    )


def test_wire_projection_omits_provider_execution_values() -> None:
    now = datetime.now(UTC)
    key = ProviderCatalogKey("codex", "codex-app-server")
    catalog = ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision="revision-a",
            expires_at=now + timedelta(minutes=1),
        ),
        models=(
            ModelCatalogEntry(
                entry_id="entry-a",
                provider_value="secret-provider-model-value",
                display_name="Model A",
                native_control_ids=("effort",),
            ),
        ),
        native_controls=(
            NativeControl(
                control_id="effort",
                kind=ControlKind.THOUGHT_LEVEL,
                display_name="Effort",
                options=(
                    NativeControlOption(
                        option_id="balanced",
                        provider_value="secret-provider-option-value",
                        display_name="Balanced",
                    ),
                ),
            ),
        ),
    )
    health = StructuredProviderHealth.derive(
        configured=HealthState.AVAILABLE,
        transport=HealthState.AVAILABLE,
        authentication=AuthenticationState.AUTHENTICATED,
        catalog=CatalogStatus.AVAILABLE,
        admission=AdmissionState.ADMITTED,
        checked_at=now,
    )
    response = ProviderCatalogResponse.from_records(
        (
            ProviderRecord(
                provider_id="codex",
                display_name="Codex",
                execution_mode="codex-app-server",
                health=health,
                catalog=catalog,
            ),
        )
    ).model_dump(mode="json")
    serialized = str(response)
    assert response["api_version"] == "v1"
    assert response["providers"][0]["catalog"]["schema_version"] == 1
    assert "provider_value" not in serialized
    assert "secret-provider-model-value" not in serialized
    assert "secret-provider-option-value" not in serialized
