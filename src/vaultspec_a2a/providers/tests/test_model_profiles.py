"""Tests for shared model-profile resolution and eligibility (model-profiles ADR).

Real configuration only: bundled presets and in-memory ``model_validate`` over
dicts. Eligibility composition is driven with real ``ProviderReadiness`` inputs
(a legitimate, injectable API argument), not a mock of the probe. Provider
readiness itself is exercised on the deterministic ``mock`` provider; the
credential/command paths are proven live in P03.
"""

from __future__ import annotations

import pytest

from vaultspec_a2a.graph.enums import MODEL_MAP, Model, Provider
from vaultspec_a2a.team.team_config import (
    AgentConfig,
    TeamConfig,
    TeamProfileRoleConfig,
    WorkerRef,
    load_team_config,
)
from vaultspec_a2a.thread.errors import ConfigError

from ..model_profiles import (
    AssignmentSource,
    ProfileAssignment,
    ProviderReadiness,
    RoleAssignment,
    acceptance_gate_reason,
    evaluate_profile_eligibility,
    probe_provider_readiness,
    resolve_effective_assignment,
    resolve_role_assignment,
)


def _agent(role: str, provider: str | None = None, capability: str | None = None):
    return AgentConfig.model_validate(
        {
            "id": f"vaultspec-{role}",
            "display_name": role,
            "role": role,
            "description": "x",
            "persona": {"system_prompt": "x"},
            "model": {"provider": provider, "capability": capability},
        }
    )


def _team(defaults: dict[str, object] | None = None) -> TeamConfig:
    return TeamConfig.model_validate(
        {
            "id": "t",
            "display_name": "T",
            "defaults": defaults or {"provider": "claude", "capability": "mid"},
            "topology": {"type": "star"},
            "workers": [{"agent_id": "vaultspec-writer"}],
        }
    )


class TestResolution:
    def test_no_overlay_matches_historical_chain(self) -> None:
        """profile_overlay=None: worker > agent > team-default, identical order."""
        team = _team({"provider": "claude", "capability": "mid"})
        agent = _agent("writer", provider="zhipu", capability="high")
        worker = WorkerRef(agent_id="vaultspec-writer")
        r = resolve_role_assignment(worker, agent, team, None)
        # agent overrides team default.
        assert r.provider == Provider.ZHIPU
        assert r.capability == Model.HIGH
        assert r.provider_source == AssignmentSource.AGENT
        assert r.capability_source == AssignmentSource.AGENT
        assert r.model_name == MODEL_MAP[Provider.ZHIPU][Model.HIGH]

    def test_worker_override_beats_agent(self) -> None:
        team = _team()
        agent = _agent("writer", provider="zhipu")
        worker = WorkerRef.model_validate(
            {"agent_id": "vaultspec-writer", "model": {"provider": "gemini"}}
        )
        r = resolve_role_assignment(worker, agent, team, None)
        assert r.provider == Provider.GEMINI
        assert r.provider_source == AssignmentSource.WORKER

    def test_profile_overlay_is_topmost(self) -> None:
        team = _team()
        agent = _agent("writer", provider="zhipu", capability="high")
        worker = WorkerRef.model_validate(
            {"agent_id": "vaultspec-writer", "model": {"provider": "gemini"}}
        )
        overlay = TeamProfileRoleConfig(provider=Provider.OPENAI, capability=Model.LOW)
        r = resolve_role_assignment(worker, agent, team, overlay)
        assert r.provider == Provider.OPENAI
        assert r.capability == Model.LOW
        assert r.provider_source == AssignmentSource.PROFILE
        assert r.capability_source == AssignmentSource.PROFILE

    def test_partial_overlay_falls_through_per_field(self) -> None:
        """A capability-only overlay leaves provider on its lower-layer source."""
        team = _team()
        agent = _agent("writer", provider="zhipu")
        worker = WorkerRef(agent_id="vaultspec-writer")
        overlay = TeamProfileRoleConfig(capability=Model.LOW)
        r = resolve_role_assignment(worker, agent, team, overlay)
        assert r.provider == Provider.ZHIPU  # agent, unchanged
        assert r.provider_source == AssignmentSource.AGENT
        assert r.capability == Model.LOW  # profile
        assert r.capability_source == AssignmentSource.PROFILE

    def test_hardcoded_default_provider_when_nothing_set(self) -> None:
        team = _team({})
        agent = _agent("writer")
        worker = WorkerRef(agent_id="vaultspec-writer")
        r = resolve_role_assignment(worker, agent, team, None)
        assert r.provider == Provider.CLAUDE
        assert r.provider_source == AssignmentSource.TEAM_DEFAULT

    def test_bundled_adr_research_team_defaults(self) -> None:
        team = load_team_config("vaultspec-adr-research")
        assignment = resolve_effective_assignment(team, "team-defaults")
        by_agent = {r.agent_id: r for r in assignment.roles}
        assert set(by_agent) == {
            "vaultspec-researcher",
            "vaultspec-synthesist",
            "vaultspec-adr-author",
            "vaultspec-doc-reviewer",
        }
        # Heterogeneous team: doc-reviewer is a different provider than the rest.
        assert by_agent["vaultspec-doc-reviewer"].provider == Provider.ZHIPU
        assert by_agent["vaultspec-researcher"].provider == Provider.CLAUDE

    def test_bundled_fast_profile_lowers_two_roles_only(self) -> None:
        team = load_team_config("vaultspec-adr-research")
        assignment = resolve_effective_assignment(team, "fast")
        by_agent = {r.agent_id: r for r in assignment.roles}
        assert by_agent["vaultspec-researcher"].capability == Model.LOW
        assert by_agent["vaultspec-researcher"].capability_source == (
            AssignmentSource.PROFILE
        )
        assert by_agent["vaultspec-doc-reviewer"].capability == Model.LOW
        # The two authoring roles are untouched (fall through to agent config).
        assert by_agent["vaultspec-synthesist"].capability_source != (
            AssignmentSource.PROFILE
        )

    def test_unknown_profile_raises_config_error(self) -> None:
        team = load_team_config("vaultspec-adr-research")
        with pytest.raises(ConfigError, match="Unknown model profile 'ghost'"):
            resolve_effective_assignment(team, "ghost")


class TestReadiness:
    def test_mock_is_always_ready(self) -> None:
        r = probe_provider_readiness(Provider.MOCK)
        assert r.ready is True
        assert r.reason is None

    def test_probe_returns_verdict_without_raising_for_every_provider(self) -> None:
        for provider in Provider:
            r = probe_provider_readiness(provider)
            assert r.provider == provider
            assert isinstance(r.ready, bool)
            # A not-ready verdict always carries a safe, non-empty reason.
            if not r.ready:
                assert r.reason


def _mock_assignment() -> ProfileAssignment:
    """A two-role assignment on the deterministic mock provider."""
    return ProfileAssignment(
        profile_id="team-defaults",
        roles=[
            RoleAssignment(
                role_id="writer",
                agent_id="a",
                provider=Provider.MOCK,
                capability=Model.MID,
                model_name="mock-mid",
                fallback_providers=[],
                provider_source=AssignmentSource.TEAM_DEFAULT,
                capability_source=AssignmentSource.TEAM_DEFAULT,
            ),
            RoleAssignment(
                role_id="reviewer",
                agent_id="b",
                provider=Provider.CLAUDE,
                capability=Model.MID,
                model_name="claude-4.6-sonnet",
                fallback_providers=[Provider.MOCK],
                provider_source=AssignmentSource.AGENT,
                capability_source=AssignmentSource.AGENT,
            ),
        ],
    )


class TestEligibility:
    def test_eligible_when_all_ready_engine_up_gate_passed(self) -> None:
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(Provider.CLAUDE, True),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=True,
            acceptance_gate_passed=True,
        )
        assert elig.eligible is True
        assert elig.reasons == []
        assert all(r.eligible for r in elig.roles)

    def test_acceptance_gate_open_keeps_profile_ineligible(self) -> None:
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(Provider.CLAUDE, True),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=True,
            acceptance_gate_passed=False,
        )
        assert elig.eligible is False
        assert acceptance_gate_reason() in elig.reasons

    def test_eligible_fallback_keeps_role_eligible(self) -> None:
        """A not-ready primary with a ready declared fallback stays eligible."""
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(
                Provider.CLAUDE, False, "no Claude OAuth token configured"
            ),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=True,
            acceptance_gate_passed=True,
        )
        # reviewer's primary (claude) is down but its fallback (mock) is ready.
        assert elig.eligible is True
        assert all(r.eligible for r in elig.roles)

    def test_no_eligible_fallback_makes_role_and_profile_ineligible(self) -> None:
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, False, "mock down"),
            Provider.CLAUDE: ProviderReadiness(Provider.CLAUDE, False, "no token"),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=True,
            acceptance_gate_passed=True,
        )
        assert elig.eligible is False
        assert any("not ready" in reason for reason in elig.reasons)

    def test_engine_unreachable_is_an_ineligibility_reason(self) -> None:
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(Provider.CLAUDE, True),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=False,
            acceptance_gate_passed=True,
        )
        assert elig.eligible is False
        assert any("engine is not reachable" in r for r in elig.reasons)
