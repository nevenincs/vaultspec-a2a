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

from vaultspec_a2a.team.team_config import load_agent_config, load_team_config
from vaultspec_a2a.thread.errors import IsolationRequiredError
from vaultspec_a2a.worker.graph_lifecycle import assert_armed_lanes_authenticated


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
