"""Tests for the armed-lane isolation compile gate (S20 fail-loud).

Real config loading (the shipped ``vaultspec-solo-coder`` preset and its agent
TOML), no mocks: only the provider factory is injected, exactly as the production
compile seam injects it, so each test states the lane's resolved
``provider``/``auth_mode`` the way the real factory would stamp it from the
environment - without depending on which tokens the test host happens to carry.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ...team.team_config import load_agent_config, load_team_config
from ...thread.errors import IsolationRequiredError
from ...worker.graph_lifecycle import assert_armed_lanes_authenticated


class _LaneModel(FakeChatModel):
    """A FakeChatModel stamped like the real factory's output for a lane.

    ``ProviderFactory`` sets ``provider`` and ``auth_mode`` on the model it
    returns (``providers/factory.py``); reproducing those two fields lets the gate
    be exercised deterministically.
    """

    provider: str = "claude"
    auth_mode: str = "none_detected"


class _LaneFactory:
    """Provider factory whose resolved models report a fixed lane + auth_mode."""

    def __init__(self, *, provider: str, auth_mode: str) -> None:
        self._provider = provider
        self._auth_mode = auth_mode

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        return _LaneModel(
            responses=["stub response"],
            provider=self._provider,
            auth_mode=self._auth_mode,
        )


def _solo_coder() -> tuple[Any, dict[str, Any]]:
    team = load_team_config("vaultspec-solo-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    return team, agent_configs


def test_solo_coder_is_armed_via_authoring_bridge() -> None:
    # The preset that leaked in S20: armed by the authoring_bridge flag, with no
    # harness mcp_servers - the case a harness-mcp-only predicate would miss.
    team, _ = _solo_coder()
    harness = team.effective_harness()
    assert harness is not None
    assert harness.authoring_bridge is True
    assert not harness.mcp_servers


def test_adr_research_arms_the_isolation_gate_without_arming_the_bridge() -> None:
    """The two arming predicates diverge, and only this shipped preset shows it.

    The compile seam runs two independent decisions off the same harness block: the
    isolation gate arms on ``authoring_bridge or mcp_servers``, while the authoring
    binding provider is built on ``authoring_bridge`` ALONE. Solo-coder and
    doc-editor set both true, so they cannot tell the predicates apart.
    ``vaultspec-adr-research`` declares harness ``mcp_servers`` with no bridge — it
    is a document-authoring topology, which the team-config validator forbids from
    arming the bridge at all — so it is the only shipped shape that pins the
    narrower predicate as narrower. Widening the binding predicate to match the
    isolation one would arm a bridge this preset must never carry.
    """
    team = load_team_config("vaultspec-adr-research")
    harness = team.effective_harness()
    assert harness is not None
    assert harness.mcp_servers
    assert harness.authoring_bridge is False
    assert team.is_document_authoring is True


def _doc_editor() -> tuple[Any, dict[str, Any]]:
    team = load_team_config("vaultspec-doc-editor")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    return team, agent_configs


def test_doc_editor_reaches_the_bridge_through_the_armed_lane_gate() -> None:
    """The solo doc-editor is armed, so its run must clear the isolation gate.

    The bridge is the preset's ONLY authoring path - its worker declares no
    filesystem write - so the arming predicate the production compile seam uses
    must recognise it, and an unauthenticated lane must be refused rather than
    spawned unisolated. Driven through the real ``assert_armed_lanes_authenticated``
    against the shipped preset, not a hand-built config.
    """
    team, agent_configs = _doc_editor()
    harness = team.effective_harness()
    assert harness is not None
    assert harness.authoring_bridge is True
    assert agent_configs["vaultspec-doc-editor"].capabilities.filesystem_write is False

    unauthenticated = _LaneFactory(provider="claude", auth_mode="none_detected")
    with pytest.raises(IsolationRequiredError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        assert_armed_lanes_authenticated(
            team, agent_configs, None, provider_factory=unauthenticated
        )

    authenticated = _LaneFactory(provider="claude", auth_mode="oauth_token")
    assert_armed_lanes_authenticated(
        team, agent_configs, None, provider_factory=authenticated
    )


def test_armed_bridge_preset_refused_without_lane_token() -> None:
    team, agent_configs = _solo_coder()
    factory = _LaneFactory(provider="claude", auth_mode="none_detected")
    with pytest.raises(IsolationRequiredError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        assert_armed_lanes_authenticated(
            team, agent_configs, None, provider_factory=factory
        )


def test_armed_preset_allowed_when_lane_authenticated() -> None:
    # Same armed preset, but the lane carries a token: no refusal.
    team, agent_configs = _solo_coder()
    factory = _LaneFactory(provider="claude", auth_mode="oauth_token")
    assert_armed_lanes_authenticated(
        team, agent_configs, None, provider_factory=factory
    )


def test_kimi_lane_exempt_from_config_home_gate() -> None:
    # Kimi rides its own inline --config isolation, so a none_detected Kimi lane is
    # NOT the config-home breach this gate guards - it must not trip (per-family
    # keying).
    team, agent_configs = _solo_coder()
    factory = _LaneFactory(provider="kimi", auth_mode="none_detected")
    assert_armed_lanes_authenticated(
        team, agent_configs, None, provider_factory=factory
    )


class _ProviderAwareFactory:
    """Stamps the model per the REQUESTED provider, not a fixed lane.

    Unlike ``_LaneFactory`` (which always returns the same stamped lane
    regardless of what was asked for), this factory answers what the real
    ``ProviderFactory`` would: codex is never in the config-home lane map, so
    it stamps ``auth_mode="oauth_token"`` too (irrelevant to this gate, since
    codex is exempt by family regardless of auth_mode) - only claude requests
    come back unauthenticated, proving the gate's verdict tracks the ACTUAL
    resolved provider per worker, not a fixed stand-in.
    """

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        if provider.value == "codex":
            return _LaneModel(
                responses=["stub response"], provider="codex", auth_mode="oauth_token"
            )
        return _LaneModel(
            responses=["stub response"], provider="claude", auth_mode="none_detected"
        )


def _adr_research() -> tuple[Any, dict[str, Any]]:
    team = load_team_config("vaultspec-adr-research")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    return team, agent_configs


def test_frozen_assignment_overriding_every_role_off_claude_is_not_refused() -> None:
    """A provider-axis profile routing every role to codex (e.g. codex-all)
    must NOT trip the claude isolation gate just because the un-overridden
    team config's own default is claude (vaultspec-adr-research's
    [team.defaults]). Regression for the gap where the gate always
    re-resolved against the team default, ignoring the run's actual frozen
    profile assignment, so a run that used no claude credential anywhere
    still refused on one it would never need.
    """
    team, agent_configs = _adr_research()
    frozen = {
        agent_id: {"provider": "codex", "capability": "mid", "fallback": []}
        for agent_id in agent_configs
    }
    assert_armed_lanes_authenticated(
        team,
        agent_configs,
        None,
        provider_factory=_ProviderAwareFactory(),
        frozen_assignment=frozen,
    )


def test_frozen_assignment_still_refuses_when_a_role_stays_on_claude() -> None:
    """A MIXED profile that leaves even one role on claude (e.g. the `codex`
    mixed profile's doc-reviewer) still refuses without a token - the gate
    stays per-role, not per-run, once the frozen assignment is honoured."""
    team, agent_configs = _adr_research()
    frozen = {
        agent_id: {"provider": "codex", "capability": "mid", "fallback": []}
        for agent_id in agent_configs
        if agent_id != "vaultspec-doc-reviewer"
    }
    with pytest.raises(IsolationRequiredError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        assert_armed_lanes_authenticated(
            team,
            agent_configs,
            None,
            provider_factory=_ProviderAwareFactory(),
            frozen_assignment=frozen,
        )
