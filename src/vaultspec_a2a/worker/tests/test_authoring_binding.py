"""Unit + live tests for the per-run authoring binding construction site.

Real objects, no mocks: the ``RunCatalogStore`` and ``AuthoringBindingProvider``
over real ``RunTokenStore``/``CatalogSnapshot`` values. The provider's binding
construction is exercised through pre-populated stores (no engine I/O) for the
deterministic cases, and a service-marked test proves the once-per-run engine
catalog fetch against a live engine.
"""

from __future__ import annotations

import os
import uuid

import pytest

from ...authoring import AgentTool, CatalogSnapshot
from ...authoring.discovery import resolve_engine
from ...thread.actor_tokens import ActorTokenBundle
from ..authoring_binding import AuthoringBindingProvider
from ..catalog_store import RunCatalogStore
from ..token_store import RunTokenStore

_ENGINE_URL = "http://127.0.0.1:8767"


def _snapshot(*names: str) -> CatalogSnapshot:
    return CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=tuple(
            AgentTool(
                name=name,
                description=name,
                input_schema={"type": "object"},
                risk_tier="read_only",
                permission_requirement="auto_permitted",
                idempotency_required=False,
                commands=(name,),
            )
            for name in names
        ),
    )


class TestRunCatalogStore:
    """The per-run catalog cache mirrors RunTokenStore's lifecycle."""

    def test_register_get_has_drop(self) -> None:
        store = RunCatalogStore()
        snap = _snapshot("read_context")
        assert store.get("t1") is None
        assert not store.has("t1")
        store.register("t1", snap)
        assert store.get("t1") is snap
        assert store.has("t1")
        assert store.active_run_count() == 1
        store.drop("t1")
        assert not store.has("t1")
        store.drop("t1")  # idempotent

    def test_register_none_is_noop(self) -> None:
        store = RunCatalogStore()
        store.register("t1", None)
        assert not store.has("t1")
        assert store.active_run_count() == 0

    def test_repr_reports_only_count(self) -> None:
        store = RunCatalogStore()
        store.register("t1", _snapshot("read_context"))
        assert repr(store) == "RunCatalogStore(active_runs=1)"


def _stores(
    *, thread_id: str, role: str, snapshot: CatalogSnapshot | None
) -> tuple[RunTokenStore, RunCatalogStore]:
    token_store = RunTokenStore()
    token_store.register(
        thread_id,
        ActorTokenBundle(tokens={role: "actor-xyz"}, engine_bearer="bearer-xyz"),
    )
    catalog_store = RunCatalogStore()
    if snapshot is not None:
        catalog_store.register(thread_id, snapshot)
    return token_store, catalog_store


class TestAuthoringBindingProvider:
    """binding_for builds a stdio binding from the run's tokens + cached catalog."""

    @pytest.mark.asyncio
    async def test_builds_stdio_binding_from_prepopulated_stores(self) -> None:
        snap = _snapshot("read_context", "propose_changeset")
        token_store, catalog_store = _stores(
            thread_id="t1", role="vaultspec-coder", snapshot=snap
        )
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=token_store,
            catalog_store=catalog_store,
        )
        binding = await provider.binding_for("t1", "vaultspec-coder")
        assert binding is not None
        # A stdio-transport binding: engine origin + run_id = thread_id, no HTTP url.
        assert binding.engine_base_url == _ENGINE_URL
        assert binding.run_id == "t1"
        assert binding.server_url is None
        assert binding.tool_names == ("read_context", "propose_changeset")
        # The cached snapshot was reused, not re-fetched.
        assert binding.snapshot is snap

    @pytest.mark.asyncio
    async def test_missing_token_coverage_yields_none(self) -> None:
        _tok, catalog_store = _stores(
            thread_id="t1", role="vaultspec-coder", snapshot=_snapshot("read_context")
        )
        empty_tokens = RunTokenStore()  # no bundle registered
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=empty_tokens,
            catalog_store=catalog_store,
        )
        assert await provider.binding_for("t1", "vaultspec-coder") is None

    @pytest.mark.asyncio
    async def test_role_without_token_yields_none(self) -> None:
        # Bearer present, but this specific role has no actor token: no binding,
        # so one role can never ride another's principal.
        token_store, catalog_store = _stores(
            thread_id="t1", role="vaultspec-coder", snapshot=_snapshot("read_context")
        )
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=token_store,
            catalog_store=catalog_store,
        )
        assert await provider.binding_for("t1", "some-other-role") is None

    def test_repr_reports_only_engine_origin(self) -> None:
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )
        assert repr(provider) == (
            f"AuthoringBindingProvider(engine_base_url={_ENGINE_URL!r})"
        )


@pytest.mark.service
@pytest.mark.asyncio
async def test_binding_for_fetches_catalog_once_per_run_live() -> None:
    """Live: binding_for fetches the engine catalog once and caches it per run."""
    endpoint = resolve_engine()
    if endpoint is None:
        pytest.skip(
            "no reachable authoring engine; set VAULTSPEC_ENGINE_SERVICE_JSON and "
            "start `vaultspec serve` per the runbook"
        )
    run_id = f"binding-live-{uuid.uuid4().hex[:8]}"
    # Mint a real actor token for the run and register it, as the executor does.
    from ...authoring import AuthoringClient, AuthoringResponse, mint_actor_token

    async with AuthoringClient(endpoint.base_url, endpoint.bearer_token) as client:
        minted = await mint_actor_token(
            client, actor_id=f"agent:{run_id}", kind="agent"
        )
        assert isinstance(minted, AuthoringResponse) and isinstance(minted.data, dict)
        raw_token = minted.data["raw_token"]

    token_store = RunTokenStore()
    token_store.register(
        run_id,
        ActorTokenBundle(
            tokens={"vaultspec-coder": raw_token},
            engine_bearer=endpoint.bearer_token,
        ),
    )
    catalog_store = RunCatalogStore()
    provider = AuthoringBindingProvider(
        engine_base_url=endpoint.base_url,
        token_store=token_store,
        catalog_store=catalog_store,
    )

    assert not catalog_store.has(run_id)
    first = await provider.binding_for(run_id, "vaultspec-coder")
    assert first is not None
    assert first.tool_names  # the engine served a non-empty catalog
    # The fetch populated the shared cache...
    assert catalog_store.has(run_id)
    cached = catalog_store.get(run_id)
    # ...and a second role's binding reuses the SAME snapshot (one fetch per run).
    second = await provider.binding_for(run_id, "vaultspec-coder")
    assert second is not None
    assert second.snapshot is cached
    if os.environ.get("VAULTSPEC_DEBUG_CATALOG"):  # pragma: no cover - diagnostic
        print(f"catalog tools={list(first.tool_names)}")
