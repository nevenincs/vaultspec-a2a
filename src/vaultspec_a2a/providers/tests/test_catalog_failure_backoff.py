"""A lane whose discovery fails is remembered, so a later read stays warm.

Discovery failure is the EXPENSIVE case: a lane fails by running its own
subprocess spawn or network call to that call's timeout, so it costs strictly
more than a lane that answers. Caching only successes therefore caches only the
cheap half - every later read re-pays the full cost of every failing lane, and a
registry with one broken lane has no warm state at all.

The cost is measured here rather than asserted in prose: the loader counts its
own invocations, because "how many times did discovery actually run" is the
defect, and a wall-clock assertion would only measure this host's mood. The
service-level test drives the real ``ProviderCatalogService`` composition so the
saving is proven where it is spent, not only in the cache in isolation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ..factory import (
    ProviderCatalogDiscovery,
    ProviderCatalogRegistration,
    ProviderFactory,
)
from ..provider_catalog import (
    AuthenticationState,
    CacheFreshness,
    CatalogRefreshCache,
    CatalogRefreshSuppressedError,
    CatalogState,
    CatalogStatus,
    HealthState,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
)
from ..provider_catalog_service import ProviderCatalogService

_LANE = ProviderCatalogKey("openai", "openai-api")


class _LaneOutageError(RuntimeError):
    """The shape a real lane fails with: a transport error carrying no catalog."""


def _catalog(key: ProviderCatalogKey, revision: str = "revision-a") -> ProviderCatalog:
    return ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=datetime.now(UTC),
            revision=revision,
        ),
        models=(
            ModelCatalogEntry(
                entry_id="entry-a",
                provider_value="provider-model-a",
                display_name="Provider model A",
            ),
        ),
    )


class _Lane:
    """A discovery loader that counts how often it actually ran."""

    def __init__(self, *, failing: bool) -> None:
        self.failing = failing
        self.attempts = 0

    async def __call__(self, requested: ProviderCatalogKey) -> ProviderCatalog:
        self.attempts += 1
        # A real failing lane burns time before it gives up. Keeping a small real
        # await here means the single-flight path is exercised rather than
        # completing synchronously inside the first caller.
        await asyncio.sleep(0.01)
        if self.failing:
            raise _LaneOutageError("lane transport refused")
        return _catalog(requested)


@pytest.mark.asyncio
async def test_a_failing_lane_is_discovered_once_across_many_reads() -> None:
    """The defect, stated as a count: N reads of a broken lane cost 1 discovery.

    Before the negative entry existed this was N, because a raising loader stored
    nothing and every read missed the cache and re-ran the full attempt.
    """
    lane = _Lane(failing=True)
    cache = CatalogRefreshCache(timedelta(minutes=5), failure_ttl=timedelta(minutes=5))

    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane)
    assert lane.attempts == 1

    for _ in range(9):
        with pytest.raises(CatalogRefreshSuppressedError) as suppressed:
            await cache.get(_LANE, lane)
        # The suppressed error names the original failure by TYPE, so the reason a
        # lane is being skipped survives into diagnostics without carrying the
        # provider's message, which can hold a credential, URL, or local path.
        assert suppressed.value.failure_type == "_LaneOutageError"
        assert suppressed.value.retry_after_seconds > 0
    assert lane.attempts == 1


@pytest.mark.asyncio
async def test_concurrent_reads_of_a_failing_lane_do_not_stampede() -> None:
    """Single-flight must cover the failing path, not only the succeeding one."""
    lane = _Lane(failing=True)
    cache = CatalogRefreshCache(timedelta(minutes=5), failure_ttl=timedelta(minutes=5))

    results = await asyncio.gather(
        *(cache.get(_LANE, lane) for _ in range(12)), return_exceptions=True
    )
    assert lane.attempts == 1
    assert all(isinstance(item, Exception) for item in results)
    assert any(isinstance(item, _LaneOutageError) for item in results)


@pytest.mark.asyncio
async def test_the_backoff_expires_so_a_recovered_lane_is_picked_up() -> None:
    """A negative entry is a delay, never a verdict: the lane is retried."""
    lane = _Lane(failing=True)
    cache = CatalogRefreshCache(
        timedelta(milliseconds=40), failure_ttl=timedelta(milliseconds=50)
    )

    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane)
    with pytest.raises(CatalogRefreshSuppressedError):
        await cache.get(_LANE, lane)
    assert lane.attempts == 1

    await asyncio.sleep(0.06)
    lane.failing = False
    snapshot = await cache.get(_LANE, lane)
    assert lane.attempts == 2
    assert snapshot.freshness is CacheFreshness.FRESH

    # The success cleared the negative entry rather than leaving it to expire.
    # Observable rather than introspected: once the SUCCESS ttl lapses, the next
    # read is a real attempt, which a surviving failure record would have refused.
    await asyncio.sleep(0.05)
    await cache.get(_LANE, lane)
    assert lane.attempts == 3


@pytest.mark.asyncio
async def test_suppression_never_discards_the_last_good_catalog() -> None:
    """The served answer is unchanged; only the cost of producing it drops.

    A caller handles a failed refresh by falling back to ``peek``. If the negative
    entry displaced the lane's last real catalog, this fix would have turned a
    stale-but-real answer into no answer at all - a behaviour change wearing a
    performance fix's clothes.
    """
    lane = _Lane(failing=False)
    cache = CatalogRefreshCache(
        timedelta(milliseconds=20), failure_ttl=timedelta(minutes=5)
    )
    await cache.get(_LANE, lane)
    await asyncio.sleep(0.03)

    lane.failing = True
    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane)
    with pytest.raises(CatalogRefreshSuppressedError):
        await cache.get(_LANE, lane)

    retained = cache.peek(_LANE)
    assert retained is not None
    assert retained.freshness is CacheFreshness.STALE
    assert retained.catalog.state.revision == "revision-a"


@pytest.mark.asyncio
async def test_an_explicit_refresh_is_never_suppressed() -> None:
    """``force_refresh`` is a caller asking to retry now; backoff must yield."""
    lane = _Lane(failing=True)
    cache = CatalogRefreshCache(timedelta(minutes=5), failure_ttl=timedelta(minutes=5))

    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane)
    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane, force_refresh=True)
    assert lane.attempts == 2


@pytest.mark.asyncio
async def test_invalidation_clears_the_backoff() -> None:
    """Invalidation is the explicit request a retained failure would refuse."""
    lane = _Lane(failing=True)
    cache = CatalogRefreshCache(timedelta(minutes=5), failure_ttl=timedelta(minutes=5))

    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane)
    cache.invalidate(_LANE)
    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, lane)
    assert lane.attempts == 2


@pytest.mark.asyncio
async def test_a_lane_invalidated_mid_failure_is_not_suppressed() -> None:
    """The generation fence governs failures exactly as it governs successes.

    A lane invalidated while its attempt was in flight was explicitly asked to
    refresh. Remembering that superseded attempt's failure would answer the new
    request with the outcome it replaced.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    attempts = 0

    async def discover(requested: ProviderCatalogKey) -> ProviderCatalog:
        nonlocal attempts
        attempts += 1
        started.set()
        await release.wait()
        raise _LaneOutageError("lane transport refused")

    cache = CatalogRefreshCache(timedelta(minutes=5), failure_ttl=timedelta(minutes=5))
    refresh = asyncio.create_task(cache.get(_LANE, discover))
    await started.wait()
    cache.invalidate(_LANE)
    release.set()
    with pytest.raises(_LaneOutageError):
        await refresh

    with pytest.raises(_LaneOutageError):
        await cache.get(_LANE, discover)
    assert attempts == 2


@pytest.mark.asyncio
async def test_a_zero_failure_ttl_disables_the_backoff_entirely() -> None:
    """The behaviour is switchable off, and off means retry, not born-expired."""
    lane = _Lane(failing=True)
    cache = CatalogRefreshCache(timedelta(minutes=5), failure_ttl=timedelta(0))

    for _ in range(3):
        with pytest.raises(_LaneOutageError):
            await cache.get(_LANE, lane)
    assert lane.attempts == 3


class _FailingLaneFactory(ProviderFactory):
    """The real factory presenting one registered lane that cannot be reached.

    Subclassing the injected factory is the service's own composition seam: the
    registration and its awaited callback are the production contract, and the
    failure is a real exception raised from a real coroutine. Only the lane
    inventory is pinned, because a host-dependent broken provider would make the
    measurement below unreproducible.
    """

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def catalog_registrations(
        self, workspace_root: Path, *, serve_in_process_lanes: bool | None = None
    ) -> tuple[ProviderCatalogRegistration, ...]:
        async def discover() -> ProviderCatalogDiscovery:
            self.attempts += 1
            await asyncio.sleep(0.05)
            raise _LaneOutageError("lane transport refused")

        return (ProviderCatalogRegistration(key=_LANE, discover=discover),)


@pytest.mark.asyncio
async def test_the_service_serves_a_failing_lane_warm_and_unchanged() -> None:
    """Through the real service: repeated reads cost one attempt, same answer.

    Both halves matter. The count is the fix; the identical record is the proof
    the fix is invisible to a client, which is the only way a caching change is
    allowed to be correct.
    """
    factory = _FailingLaneFactory()
    service = ProviderCatalogService(factory=factory)
    workspace = str(Path(__file__).resolve().parents[3])

    first = await service.records(workspace)
    assert factory.attempts == 1

    for _ in range(5):
        later = await service.records(workspace)
        assert factory.attempts == 1
        assert [record.provider_id for record in later] == [
            record.provider_id for record in first
        ]
        assert later[0].catalog.state.status is first[0].catalog.state.status
        assert later[0].health.selectable is first[0].health.selectable
        assert later[0].health.reasons == first[0].health.reasons

    # The served answer for an unreachable lane is still the honest one: no
    # catalog, not selectable, and a reason a client can render.
    assert first[0].catalog.state.status is CatalogStatus.UNAVAILABLE
    assert first[0].catalog.models == ()
    assert first[0].health.selectable is False
    assert first[0].health.authentication is AuthenticationState.UNKNOWN
    assert first[0].health.configured is HealthState.UNKNOWN
