"""Tests for the compile-time authoring-attachment gate (codex-authoring-bridge fix).

Real config loading (the shipped ``vaultspec-solo-coder`` preset and its agent
TOML), no mocks: only the provider factory is injected, exactly as the production
compile seam injects it -- mirroring ``test_isolation_gate.py``'s pattern for the
sibling ``assert_armed_lanes_authenticated`` gate.

Before this gate existed, a harness-armed preset whose resolved provider had no
attachment surface (neither ``with_mcp_servers`` nor ``with_authoring_mcp_server``)
started the run anyway: ``_acp_authoring.attach_authoring_tools`` returned the
model UNCHANGED, and the agent burned its full step timeout with tools that never
mounted. ``assert_armed_authoring_attachable`` asks the identical question at
compile time, before any subprocess spawns, so the refusal is loud and immediate.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ...team.team_config import load_agent_config, load_team_config
from ...thread.errors import ConfigError
from ...worker.graph_lifecycle import assert_armed_authoring_attachable


class _NoSurfaceModel(FakeChatModel):
    """A model with neither authoring attachment surface -- the refused shape."""


class _AcpSurfaceModel(FakeChatModel):
    """A model exposing the ACP lane's ``with_mcp_servers`` surface."""

    def with_mcp_servers(
        self, mcp_servers: Any, allowed_tools: Any = None
    ) -> "_AcpSurfaceModel":
        return self


class _CodexSurfaceModel(FakeChatModel):
    """A model exposing the Codex lane's ``with_authoring_mcp_server`` surface."""

    def with_authoring_mcp_server(self, spec: Any) -> "_CodexSurfaceModel":
        return self


class _FixedFactory:
    """Provider factory whose resolved models are always the same fixed instance."""

    def __init__(self, model: FakeChatModel) -> None:
        self._model = model

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        return self._model


def _solo_coder() -> tuple[Any, dict[str, Any]]:
    team = load_team_config("vaultspec-solo-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    return team, agent_configs


def test_solo_coder_is_armed_via_authoring_bridge() -> None:
    # Same armed shape test_isolation_gate.py pins: authoring_bridge=true, no
    # declared harness mcp_servers -- the case a harness-mcp-only predicate
    # would miss, and exactly the S20-class gap this gate closes.
    team, _ = _solo_coder()
    harness = team.effective_harness()
    assert harness is not None
    assert harness.authoring_bridge is True


def test_provider_with_no_attach_surface_is_refused_at_compile_time() -> None:
    team, agent_configs = _solo_coder()
    harness = team.effective_harness()
    factory = _FixedFactory(_NoSurfaceModel(responses=["stub"]))
    with pytest.raises(ConfigError, match="no authoring attachment surface"):
        assert_armed_authoring_attachable(
            team, agent_configs, None, harness=harness, provider_factory=factory
        )


def test_acp_lane_provider_is_allowed() -> None:
    team, agent_configs = _solo_coder()
    harness = team.effective_harness()
    factory = _FixedFactory(_AcpSurfaceModel(responses=["stub"]))
    assert_armed_authoring_attachable(
        team, agent_configs, None, harness=harness, provider_factory=factory
    )


def test_codex_lane_provider_is_allowed() -> None:
    team, agent_configs = _solo_coder()
    harness = team.effective_harness()
    factory = _FixedFactory(_CodexSurfaceModel(responses=["stub"]))
    assert_armed_authoring_attachable(
        team, agent_configs, None, harness=harness, provider_factory=factory
    )


def test_unarmed_preset_is_a_noop_regardless_of_provider_surface() -> None:
    # harness=None (the no-[team.harness]-block shape): the gate must not even
    # look at the provider, so a no-surface model is fine.
    team, agent_configs = _solo_coder()
    factory = _FixedFactory(_NoSurfaceModel(responses=["stub"]))
    assert_armed_authoring_attachable(
        team, agent_configs, None, harness=None, provider_factory=factory
    )


def test_harness_without_authoring_bridge_is_a_noop() -> None:
    # A harness declared but with authoring_bridge=False (e.g. an mcp_servers-only
    # preset): out of scope for this gate by design (see the function's own
    # docstring -- the harness-mcp_servers-only case is proven to reach every
    # known provider's own delivery mechanism elsewhere).
    team, agent_configs = _solo_coder()
    harness = team.effective_harness()
    assert harness is not None
    unarmed_harness = harness.model_copy(update={"authoring_bridge": False})
    factory = _FixedFactory(_NoSurfaceModel(responses=["stub"]))
    assert_armed_authoring_attachable(
        team,
        agent_configs,
        None,
        harness=unarmed_harness,
        provider_factory=factory,
    )
