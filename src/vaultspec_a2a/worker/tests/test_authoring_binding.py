"""Unit + live tests for the per-run authoring binding construction site.

Real objects, no mocks: the ``RunCatalogStore`` and ``AuthoringBindingProvider``
over real ``RunTokenStore``/``CatalogSnapshot`` values. The provider's binding
construction is exercised through pre-populated stores (no engine I/O) for the
deterministic cases, and a service-marked test proves the once-per-run engine
catalog fetch against a live engine.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING

import pytest

from ...authoring import AgentTool, CatalogSnapshot
from ...testing import mint_raw_token
from ...thread.actor_tokens import ActorTokenBundle
from ..authoring_binding import AuthoringBindingProvider
from ..catalog_store import RunCatalogStore
from ..token_store import RunTokenStore

if TYPE_CHECKING:
    from ...authoring.discovery import EngineEndpoint

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

    def test_register_get_drop(self) -> None:
        store = RunCatalogStore()
        snap = _snapshot("read_context")
        assert store.get("t1") is None
        store.register("t1", snap)
        assert store.get("t1") is snap
        assert repr(store) == "RunCatalogStore(active_runs=1)"
        store.drop("t1")
        assert store.get("t1") is None
        store.drop("t1")  # idempotent

    def test_register_none_is_noop(self) -> None:
        store = RunCatalogStore()
        store.register("t1", None)
        assert store.get("t1") is None
        assert repr(store) == "RunCatalogStore(active_runs=0)"

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
        assert binding.call_scope == "vaultspec-coder"
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
    async def test_registered_bundle_without_bearer_yields_none(self) -> None:
        # The bundle is REGISTERED and carries this role's actor token, but the
        # dispatch supplied no engine bearer. The provider does not substitute
        # one from engine discovery (that would pair a bearer with an origin it
        # was not minted for), so the bridge stays unarmed rather than armed
        # against the wrong engine.
        token_store = RunTokenStore()
        token_store.register(
            "t1",
            ActorTokenBundle(
                tokens={"vaultspec-coder": "actor-xyz"}, engine_bearer=None
            ),
        )
        assert token_store.actor_token("t1", "vaultspec-coder") == "actor-xyz"
        assert token_store.engine_bearer("t1") is None

        catalog_store = RunCatalogStore()
        catalog_store.register("t1", _snapshot("read_context"))
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=token_store,
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

    @pytest.mark.asyncio
    async def test_missing_bearer_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Verify missing engine bearer logs a warning with thread_id and agent_id.
        token_store = RunTokenStore()
        token_store.register(
            "t1",
            ActorTokenBundle(
                tokens={"vaultspec-coder": "actor-xyz"}, engine_bearer=None
            ),
        )
        catalog_store = RunCatalogStore()
        catalog_store.register("t1", _snapshot("read_context"))
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=token_store,
            catalog_store=catalog_store,
        )
        with caplog.at_level(logging.WARNING):
            binding = await provider.binding_for("t1", "vaultspec-coder")
        assert binding is None
        assert (
            "authoring bridge unarmed for thread_id=t1 agent_id=vaultspec-coder: "
            "missing engine_bearer"
        ) in caplog.text

    @pytest.mark.asyncio
    async def test_missing_actor_token_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Verify missing actor token logs a warning with thread_id and agent_id.
        token_store = RunTokenStore()
        token_store.register(
            "t1",
            ActorTokenBundle(tokens={}, engine_bearer="bearer-xyz"),
        )
        catalog_store = RunCatalogStore()
        catalog_store.register("t1", _snapshot("read_context"))
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=token_store,
            catalog_store=catalog_store,
        )
        with caplog.at_level(logging.WARNING):
            binding = await provider.binding_for("t1", "vaultspec-coder")
        assert binding is None
        assert (
            "authoring bridge unarmed for thread_id=t1 agent_id=vaultspec-coder: "
            "missing actor_token"
        ) in caplog.text

    def test_repr_reports_only_engine_origin(self) -> None:
        provider = AuthoringBindingProvider(
            engine_base_url=_ENGINE_URL,
            token_store=RunTokenStore(),
            catalog_store=RunCatalogStore(),
        )
        assert repr(provider) == (
            f"AuthoringBindingProvider(engine_base_url={_ENGINE_URL!r})"
        )


async def _live_coder_provider(
    live_engine: EngineEndpoint, run_id: str
) -> tuple[AuthoringBindingProvider, RunCatalogStore]:
    """Mint a real actor token for *run_id* and build a live-engine provider.

    Shared by the once-per-run and concurrent-fetch live proofs below, which
    differ only in how they call ``binding_for`` after this arrangement.
    """
    from ...authoring import AuthoringClient

    async with AuthoringClient(
        live_engine.base_url, live_engine.bearer_token
    ) as client:
        raw_token = await mint_raw_token(client, f"agent:{run_id}", "agent")

    token_store = RunTokenStore()
    token_store.register(
        run_id,
        ActorTokenBundle(
            tokens={"vaultspec-coder": raw_token},
            engine_bearer=live_engine.bearer_token,
        ),
    )
    catalog_store = RunCatalogStore()
    provider = AuthoringBindingProvider(
        engine_base_url=live_engine.base_url,
        token_store=token_store,
        catalog_store=catalog_store,
    )
    return provider, catalog_store


@pytest.mark.service
@pytest.mark.asyncio
async def test_binding_for_fetches_catalog_once_per_run_live(
    live_engine: EngineEndpoint,
) -> None:
    """Live: binding_for fetches the engine catalog once and caches it per run."""
    run_id = f"binding-live-{uuid.uuid4().hex[:8]}"
    provider, catalog_store = await _live_coder_provider(live_engine, run_id)

    assert catalog_store.get(run_id) is None
    first = await provider.binding_for(run_id, "vaultspec-coder")
    assert first is not None
    assert first.tool_names  # the engine served a non-empty catalog
    # The fetch populated the shared cache...
    cached = catalog_store.get(run_id)
    assert cached is not None
    # ...and a second role's binding reuses the SAME snapshot (one fetch per run).
    second = await provider.binding_for(run_id, "vaultspec-coder")
    assert second is not None
    assert second.snapshot is cached
    if os.environ.get("VAULTSPEC_A2A_DEBUG_CATALOG"):  # pragma: no cover - diagnostic
        print(f"catalog tools={list(first.tool_names)}")


@pytest.mark.service
@pytest.mark.asyncio
async def test_binding_for_concurrent_fetches_share_one_snapshot_live(
    live_engine: EngineEndpoint,
) -> None:
    """Live: concurrent binding_for on an empty cache fetches once (per-thread lock).

    Without the lock the two workers would each fetch and the second register would
    overwrite the first, handing them DIFFERENT snapshot objects; the lock makes
    both share the one cached snapshot - the star-fan-out double-fetch guard.
    """
    import asyncio as _asyncio

    run_id = f"binding-conc-{uuid.uuid4().hex[:8]}"
    provider, catalog_store = await _live_coder_provider(live_engine, run_id)
    first, second = await _asyncio.gather(
        provider.binding_for(run_id, "vaultspec-coder"),
        provider.binding_for(run_id, "vaultspec-coder"),
    )
    assert first is not None and second is not None
    assert first.snapshot is second.snapshot
    assert repr(catalog_store) == "RunCatalogStore(active_runs=1)"
