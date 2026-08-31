"""Real-behavior coverage for normalized provider catalog contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from ..provider_catalog import (
    MAX_DISPLAY_LENGTH,
    AdmissionState,
    AuthenticationState,
    CacheFreshness,
    CatalogRefreshCache,
    CatalogRefreshInvalidatedError,
    CatalogState,
    CatalogStatus,
    ControlKind,
    ControlSelection,
    HealthState,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
    SelectionReference,
    StructuredProviderHealth,
)


def _catalog(key: ProviderCatalogKey, revision: str = "revision-a") -> ProviderCatalog:
    checked_at = datetime.now(UTC)
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=checked_at,
            revision=revision,
            expires_at=checked_at + timedelta(minutes=1),
        ),
        models=(
            ModelCatalogEntry(
                entry_id="entry-a",
                provider_value="provider-model-a",
                display_name="Provider model A",
                capabilities=("generate",),
                native_control_ids=("thinking",),
            ),
        ),
        native_controls=(
            NativeControl(
                control_id="thinking",
                kind=ControlKind.THOUGHT_LEVEL,
                display_name="Thinking",
                options=(
                    NativeControlOption(
                        option_id="balanced",
                        provider_value="provider-balanced",
                        display_name="Balanced",
                    ),
                ),
                default_option_id="balanced",
            ),
        ),
    )


def test_catalog_contract_is_immutable_normalized_and_opaque() -> None:
    key = ProviderCatalogKey(provider_id="provider-a", execution_mode="lane-a")
    catalog = _catalog(key)
    assert catalog.model("entry-a") is not None
    assert catalog.models[0].provider_value == "provider-model-a"
    assert hash(catalog)
    with pytest.raises(ValueError, match="duplicates"):
        ProviderCatalog(
            key=key,
            state=catalog.state,
            models=(catalog.models[0], catalog.models[0]),
        )


def test_catalog_contract_detaches_every_caller_owned_sequence() -> None:
    key = ProviderCatalogKey(provider_id="provider-a", execution_mode="lane-a")
    capabilities = ["generate"]
    native_control_ids = ["thinking"]
    options = [NativeControlOption("balanced", "provider-balanced", "Balanced")]
    models = [
        ModelCatalogEntry(
            "entry-a",
            "provider-model-a",
            "Provider model A",
            capabilities=cast("tuple[str, ...]", capabilities),
            native_control_ids=cast("tuple[str, ...]", native_control_ids),
        )
    ]
    controls = [
        NativeControl(
            "thinking",
            ControlKind.THOUGHT_LEVEL,
            "Thinking",
            cast("tuple[NativeControlOption, ...]", options),
        )
    ]
    catalog = ProviderCatalog(
        key,
        CatalogState(CatalogStatus.AVAILABLE, datetime.now(UTC), "revision-a"),
        cast("tuple[ModelCatalogEntry, ...]", models),
        cast("tuple[NativeControl, ...]", controls),
    )
    selections = [ControlSelection("thinking", "balanced")]
    selection = SelectionReference(
        key.provider_id,
        key.execution_mode,
        "revision-a",
        "entry-a",
        cast("tuple[ControlSelection, ...]", selections),
    )
    capabilities.clear()
    native_control_ids.clear()
    options.clear()
    models.clear()
    controls.clear()
    selections.clear()
    assert catalog.models[0].capabilities == ("generate",)
    assert catalog.models[0].native_control_ids == ("thinking",)
    assert catalog.native_controls[0].options[0].option_id == "balanced"
    assert selection.controls[0].control_id == "thinking"


def test_catalog_contract_rejects_unbounded_display_metadata() -> None:
    with pytest.raises(ValueError, match=f"{MAX_DISPLAY_LENGTH}-character limit"):
        ModelCatalogEntry("entry-a", "provider-model-a", "x" * (MAX_DISPLAY_LENGTH + 1))


def test_catalog_rejects_model_references_to_unadvertised_controls() -> None:
    key = ProviderCatalogKey("provider-a", "lane-a")
    with pytest.raises(ValueError, match="name advertised controls"):
        ProviderCatalog(
            key=key,
            state=CatalogState(
                CatalogStatus.AVAILABLE,
                datetime.now(UTC),
                "revision-a",
            ),
            models=(
                ModelCatalogEntry(
                    "entry-a",
                    "provider-model-a",
                    "Provider model A",
                    native_control_ids=("missing",),
                ),
            ),
        )


def test_structured_health_derives_selectability_from_independent_axes() -> None:
    healthy = StructuredProviderHealth.derive(
        configured=HealthState.AVAILABLE,
        transport=HealthState.AVAILABLE,
        authentication=AuthenticationState.AUTHENTICATED,
        catalog=CatalogStatus.AVAILABLE,
        admission=AdmissionState.ADMITTED,
        checked_at=datetime.now(UTC),
    )
    unproven = StructuredProviderHealth.derive(
        configured=HealthState.AVAILABLE,
        transport=HealthState.AVAILABLE,
        authentication=AuthenticationState.UNKNOWN,
        catalog=CatalogStatus.AVAILABLE,
        admission=AdmissionState.UNKNOWN,
        reasons=("authentication and completed-turn admission are unproven",),
        checked_at=datetime.now(UTC),
    )
    assert healthy.selectable is True
    assert unproven.selectable is False
    assert unproven.configured is HealthState.AVAILABLE


def test_selection_fingerprint_is_order_independent_but_value_sensitive() -> None:
    first = SelectionReference(
        "provider-a",
        "lane-a",
        "revision-a",
        "entry-a",
        (
            ControlSelection("thinking", "balanced"),
            ControlSelection("service", "standard"),
        ),
    )
    reordered = replace(first, controls=tuple(reversed(first.controls)))
    changed = replace(first, controls=(ControlSelection("thinking", "extended"),))
    assert first.fingerprint() == reordered.fingerprint()
    assert first.fingerprint() != changed.fingerprint()


@pytest.mark.asyncio
async def test_refresh_cache_coalesces_concurrent_loads_and_exposes_staleness() -> None:
    key = ProviderCatalogKey("provider-a", "lane-a")
    cache = CatalogRefreshCache(timedelta(milliseconds=30))
    calls = 0

    async def discover(requested: ProviderCatalogKey) -> ProviderCatalog:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return _catalog(requested)

    snapshots = await asyncio.gather(*(cache.get(key, discover) for _ in range(12)))
    assert calls == 1
    assert all(item.freshness is CacheFreshness.FRESH for item in snapshots)
    await asyncio.sleep(0.04)
    stale = cache.peek(key)
    assert stale is not None
    assert stale.freshness is CacheFreshness.STALE
    assert (await cache.get(key, discover)).freshness is CacheFreshness.FRESH
    forced = await asyncio.gather(
        *(cache.get(key, discover, force_refresh=True) for _ in range(12))
    )
    assert calls == 3
    assert all(item.freshness is CacheFreshness.FRESH for item in forced)


@pytest.mark.asyncio
async def test_failed_refresh_preserves_the_previous_stale_snapshot() -> None:
    key = ProviderCatalogKey("provider-a", "lane-a")
    cache = CatalogRefreshCache(timedelta(minutes=1))

    async def discover(requested: ProviderCatalogKey) -> ProviderCatalog:
        return _catalog(requested)

    await cache.get(key, discover)
    cache.invalidate(key)

    async def unavailable(_requested: ProviderCatalogKey) -> ProviderCatalog:
        raise RuntimeError("catalog endpoint unavailable")

    with pytest.raises(RuntimeError, match="catalog endpoint unavailable"):
        await cache.get(key, unavailable)
    retained = cache.peek(key)
    assert retained is not None
    assert retained.freshness is CacheFreshness.STALE


@pytest.mark.asyncio
async def test_refresh_cache_never_outlives_provider_catalog_expiry() -> None:
    key = ProviderCatalogKey("provider-a", "lane-a")
    cache = CatalogRefreshCache(timedelta(minutes=5))

    async def discover(requested: ProviderCatalogKey) -> ProviderCatalog:
        catalog = _catalog(requested)
        checked_at = datetime.now(UTC) - timedelta(seconds=2)
        return replace(
            catalog,
            state=CatalogState(
                CatalogStatus.AVAILABLE,
                checked_at,
                "revision-expired",
                checked_at + timedelta(seconds=1),
            ),
        )

    snapshot = await cache.get(key, discover)
    assert snapshot.freshness is CacheFreshness.STALE
    assert snapshot.expires_at < datetime.now(UTC)


@pytest.mark.asyncio
async def test_invalidation_fences_an_in_flight_refresh_result() -> None:
    key = ProviderCatalogKey("provider-a", "lane-a")
    cache = CatalogRefreshCache(timedelta(minutes=1))
    started = asyncio.Event()
    release = asyncio.Event()

    async def discover(requested: ProviderCatalogKey) -> ProviderCatalog:
        started.set()
        await release.wait()
        return _catalog(requested)

    refresh = asyncio.create_task(cache.get(key, discover))
    await started.wait()
    cache.invalidate(key)
    release.set()
    with pytest.raises(CatalogRefreshInvalidatedError):
        await refresh
    assert cache.peek(key) is None


@pytest.mark.asyncio
async def test_bounded_cache_evicts_an_expired_inactive_lane() -> None:
    first = ProviderCatalogKey("provider-a", "lane-a")
    second = ProviderCatalogKey("provider-b", "lane-b")
    cache = CatalogRefreshCache(timedelta(milliseconds=10), max_lanes=1)

    async def discover(requested: ProviderCatalogKey) -> ProviderCatalog:
        return _catalog(requested)

    await cache.get(first, discover)
    await asyncio.sleep(0.02)
    await cache.get(second, discover)
    assert cache.peek(first) is None
    assert cache.peek(second) is not None
