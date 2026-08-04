"""Live proof of the agent-harness refuse/serve binding at the gateway boundary.

Real gateway app on a real socket, real eligibility service, real
``provision_workspace`` (a genuine ``vaultspec-core install``) - no mocks. Proves
the wiring is LIVE rather than inert:

- an UNPROVISIONED workspace for a document-authoring preset is REFUSED at
  run-start with the harness reason (before any dispatch) and SERVED as
  unavailable at discovery;
- a PROVISIONED workspace clears the harness gate at both surfaces.

The refusal fires in the eligibility gate before the worker is ever reached, so
no worker double is exercised on the proven path.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import httpx
import pytest

from ...cli.provision import provision_workspace
from ...team.team_config import load_team_config
from .conftest import async_catalog_run_fields, make_app
from .test_gateway_live import _live_server

if TYPE_CHECKING:
    from pathlib import Path

_AUTHORING = "vaultspec-adr-research"


def _authoring_roles() -> tuple[str, ...]:
    """The preset's required agent ids, read from the preset itself.

    Derived rather than listed: these tests exist to prove the HARNESS refuses a
    run, which they can only do when every other gate passes, so a bundle that
    silently falls behind the preset turns them into token-gate tests wearing a
    harness-gate name. A hardcoded copy did exactly that when the preset gained a
    plan-author role, so the roles now come from the same place the gate reads.
    """
    return tuple(worker.agent_id for worker in load_team_config(_AUTHORING).workers)


pytestmark = pytest.mark.skipif(
    shutil.which("vaultspec-core") is None and shutil.which("uvx") is None,
    reason="vaultspec-core CLI not resolvable; cannot provision a real workspace",
)


def _full_bundle() -> dict:
    """A complete per-role actor-token bundle so only the harness can refuse."""
    return {
        "tokens": {role: f"tok-{role}" for role in _authoring_roles()},
        "engine_bearer": "bearer",
    }


async def _run_start_body(
    client: httpx.AsyncClient, workspace_root: Path, *, run_id: str
) -> dict:
    """A body complete enough that only the HARNESS can refuse it.

    Only the ``selection`` is taken from the catalog helper: the ``metadata`` it
    also returns is anchored on the cwd, and these tests must keep their own
    ``workspace_root`` - that field IS the variable under test. The selection is
    derived against this test's workspace so the run reaches the harness gate on
    the merits rather than on a malformed body.
    """
    fields = await async_catalog_run_fields(client, workspace_root=str(workspace_root))
    return {
        "team_preset": _AUTHORING,
        "message": "research the thing",
        "feature_tag": "harness-edge",
        "actor_tokens": _full_bundle(),
        "metadata": {"workspace_root": str(workspace_root)},
        "run_id": run_id,
        "selection": fields["selection"],
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_unprovisioned_workspace_refused_at_run_start(
    session_factory, checkpointer, tmp_path: Path
) -> None:
    """A complete request into a bare workspace is refused on the harness alone.

    Post-Path-B (architect arbitration): the rules surface resolves via the
    bundled in-process defaults, so a bare workspace is refused on the TEMPLATES
    surface (which has no bundled fallback), never the rules one. The refuse
    binding is unchanged - a bare workspace still cannot start an authoring run.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        resp = await client.post(
            "/v1/runs",
            json=await _run_start_body(
                client, tmp_path, run_id="harness-unprovisioned"
            ),
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "harness" in detail.lower()
        assert "templates missing" in detail
        # The disputed pre-Path-B rules reason is gone: bundled defaults satisfy
        # the rules surface even on a bare workspace.
        assert "rules corpus" not in detail
        # The safe reason names WHAT is missing, never the workspace path.
        assert str(tmp_path) not in detail
        # The refusal happened in the eligibility gate, before any dispatch.
        assert worker.dispatches == []


@pytest.mark.asyncio(loop_scope="function")
async def test_unprovisioned_preset_serves_harness_reason_at_discovery(
    session_factory, checkpointer, tmp_path: Path
) -> None:
    """Discovery marks the authoring preset unavailable with the harness reason."""
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        resp = await client.get("/v1/presets", params={"workspace_root": str(tmp_path)})
        assert resp.status_code == 200
        by_id = {p["id"]: p for p in resp.json()["presets"]}
        profiles = by_id[_AUTHORING]["profiles"]
        # Every profile of the unprovisioned authoring preset carries the harness
        # reason among its unavailable reasons; none leaks the workspace path.
        for profile in profiles:
            reasons = " ".join(profile["unavailable_reasons"])
            assert "harness" in reasons.lower()
            assert str(tmp_path) not in reasons


@pytest.mark.asyncio(loop_scope="function")
async def test_provisioned_workspace_clears_the_harness_gate_at_run_start(
    session_factory, checkpointer, tmp_path: Path
) -> None:
    """A real provision clears the harness gate; any refusal is not the harness."""
    ws = tmp_path / "ws"
    result = provision_workspace(ws)
    assert result.ok, result.harness.reasons

    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        resp = await client.post(
            "/v1/runs",
            json=await _run_start_body(client, ws, run_id="harness-provisioned"),
        )
        # The harness gate is cleared: the run either dispatches (201) or is
        # refused for a NON-harness reason (e.g. provider readiness), but never
        # for the harness.
        if resp.status_code != 201:
            detail = resp.json()["detail"]
            assert "harness" not in detail.lower()


@pytest.mark.asyncio(loop_scope="function")
async def test_provisioned_preset_has_no_harness_reason_at_discovery(
    session_factory, checkpointer, tmp_path: Path
) -> None:
    """Discovery over a provisioned workspace serves no harness reason."""
    ws = tmp_path / "ws"
    result = provision_workspace(ws)
    assert result.ok, result.harness.reasons

    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        resp = await client.get("/v1/presets", params={"workspace_root": str(ws)})
        assert resp.status_code == 200
        by_id = {p["id"]: p for p in resp.json()["presets"]}
        for profile in by_id[_AUTHORING]["profiles"]:
            reasons = " ".join(profile["unavailable_reasons"])
            assert "harness" not in reasons.lower()


def test_probe_harness_refuses_authoring_preset_without_workspace() -> None:
    """An authoring preset with no resolved workspace is not silently skipped."""
    from ...team.team_config import load_team_config
    from ..routes.gateway import _probe_harness

    verdict = _probe_harness(load_team_config(_AUTHORING), None)
    assert verdict is not None
    assert verdict.ready is False
    assert "no workspace resolved" in " ".join(verdict.reasons)


def test_probe_harness_is_none_for_non_authoring_without_workspace() -> None:
    """A non-authoring preset stays a no-op (None) even with no workspace."""
    from ...team.team_config import load_team_config
    from ..routes.gateway import _probe_harness

    assert _probe_harness(load_team_config("mock-success-single"), None) is None


@pytest.mark.asyncio(loop_scope="function")
async def test_workspaceless_authoring_run_is_refused(
    session_factory, checkpointer
) -> None:
    """An authoring run with a top-level feature but NO workspace is hard-refused.

    The bypass: a top-level feature_tag satisfies the feature gate independent of
    metadata, so without this refusal a workspaceless authoring run would clear
    feature + tokens and dispatch with the harness gate silently skipped.

    The property defended here is that such a run never dispatches. It is now
    refused EARLIER and more broadly than by the harness: every run must name an
    active project, so the workspaceless body is rejected by that universal gate
    before the harness is consulted at all. That is a strictly stronger closure of
    the same bypass, so this asserts the refusal that actually fires rather than
    the harness wording it used to. The harness's own workspaceless verdict is not
    lost coverage - ``test_probe_harness_refuses_authoring_preset_without_workspace``
    pins it directly.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        resp = await client.post(
            "/v1/runs",
            json={
                "team_preset": _AUTHORING,
                "message": "research it",
                "feature_tag": "harness-edge",
                "actor_tokens": _full_bundle(),
                "run_id": "harness-workspaceless",
                # A structurally valid selection, so the refusal under test is the
                # harness one and not a schema rejection. The eligibility gate runs
                # BEFORE the selection is revalidated, so this selection is never
                # anchored - which is exactly the workspaceless condition asserted.
                "selection": (await async_catalog_run_fields(client))["selection"],
                # No metadata block -> ws_root is None.
            },
        )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "requires an active project" in detail
        assert "workspace_root is missing" in detail
        # The refusal names WHAT is missing without naming the caller's paths.
        assert "never inferred from the serving process" in detail
        # The load-bearing half: the run was refused, not merely reported on.
        assert worker.dispatches == []
