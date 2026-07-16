"""Live proof of the agent-harness refuse/serve binding at the gateway boundary
(agent-harness-provisioning P02.S04).

Real gateway app on a real socket, real eligibility service, real
``provision_workspace`` (a genuine ``vaultspec-core install``) - no mocks. Proves
the P02.S03 wiring is LIVE rather than inert:

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
from .conftest import make_app
from .test_gateway_live import _live_server

if TYPE_CHECKING:
    from pathlib import Path

_AUTHORING = "vaultspec-adr-research"
_ROLES = (
    "vaultspec-researcher",
    "vaultspec-synthesist",
    "vaultspec-adr-author",
    "vaultspec-doc-reviewer",
)

pytestmark = pytest.mark.skipif(
    shutil.which("vaultspec-core") is None and shutil.which("uvx") is None,
    reason="vaultspec-core CLI not resolvable; cannot provision a real workspace",
)


def _full_bundle() -> dict:
    """A complete per-role actor-token bundle so only the harness can refuse."""
    return {
        "tokens": {role: f"tok-{role}" for role in _ROLES},
        "engine_bearer": "bearer",
    }


def _run_start_body(workspace_root: Path) -> dict:
    return {
        "team_preset": _AUTHORING,
        "message": "research the thing",
        "feature_tag": "harness-edge",
        "actor_tokens": _full_bundle(),
        "metadata": {"workspace_root": str(workspace_root)},
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_unprovisioned_workspace_refused_at_run_start(
    session_factory, checkpointer, tmp_path: Path
) -> None:
    """A complete request into a bare workspace is refused on the harness alone."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=30.0) as client,
    ):
        resp = await client.post("/v1/runs", json=_run_start_body(tmp_path))
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "harness" in detail.lower()
        assert "rules corpus" in detail or "not provisioned" in detail
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
        resp = await client.post("/v1/runs", json=_run_start_body(ws))
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
                # No metadata block -> ws_root is None.
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "harness" in detail.lower()
        assert "no workspace resolved" in detail
        assert worker.dispatches == []
