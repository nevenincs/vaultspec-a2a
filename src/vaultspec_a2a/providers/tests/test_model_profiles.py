"""Tests for shared model-profile resolution and eligibility.

Real configuration only: bundled presets and in-memory ``model_validate`` over
dicts. Eligibility composition is driven with real ``ProviderReadiness`` inputs
(a legitimate, injectable API argument), not a mock of the probe. Provider
readiness itself is exercised on the deterministic ``mock`` provider; the
credential/command paths are proven live in P03.
"""

from __future__ import annotations

import pytest

from ...context.harness import HarnessReadiness
from ...control.config import settings
from ...graph.enums import Model, Provider
from ...team.team_config import (
    AgentConfig,
    TeamConfig,
    TeamProfileRoleConfig,
    WorkerRef,
    load_team_config,
)
from ...thread.errors import ConfigError
from ..model_profiles import (
    AssignmentSource,
    ProfileAssignment,
    ProviderReadiness,
    RoleAssignment,
    evaluate_profile_eligibility,
    freeze_assignment,
    frozen_from_record,
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


def _legacy_team() -> TeamConfig:
    """A team that still declares provider policy, as a pre-contract one did.

    The freeze/digest/replay contract below is a LEGACY read path: it exists so a
    run frozen before the catalog contract stays restartable. Bundled product
    presets no longer declare a provider, so driving these cases from one would
    prove nothing about freezing and would only re-assert the absence that
    ``TestResolution`` already covers. This supplies the shape those older runs
    actually had - real config through ``model_validate``, not a stand-in.
    """
    return TeamConfig.model_validate(
        {
            "id": "legacy",
            "display_name": "Legacy",
            "defaults": {"provider": "claude", "capability": "mid"},
            "topology": {"type": "star"},
            "workers": [
                {"agent_id": "vaultspec-researcher"},
                {"agent_id": "vaultspec-synthesist"},
            ],
            "profiles": {
                "fast": {
                    "display_name": "Fast",
                    "roles": {
                        "vaultspec-researcher": {"capability": "low"},
                        "vaultspec-synthesist": {"capability": "low"},
                    },
                }
            },
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
        # The legacy chain resolves the provider and the capability tier, but it
        # cannot NAME an external model: those names belong to the catalog that
        # provider serves and are frozen per role at run start. The empty string
        # is this surface's established "no name" value, and it cannot leak into
        # a run - the compiler refuses a blank frozen model_name outright rather
        # than constructing against it.
        assert r.model_name == ""

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

    def test_nothing_declared_resolves_to_no_provider(self) -> None:
        """No layer declares a provider, so the role resolves to an ABSENCE.

        This replaces a test that asserted a hardcoded ``Provider.CLAUDE``
        fallback. Two things were wrong with it. The fallback itself is an
        implicit provider default, which the catalog contract retires: a
        repository-authored lane chosen because nothing declared one is
        indistinguishable, downstream, from a lane someone actually chose.

        And it never exercised that fallback anyway - it passed ``_team({})``,
        and the helper's ``defaults or {...}`` treats an empty dict as falsy, so
        the team came back with claude defaults and the test asserted the
        team-default branch under a name claiming otherwise. The explicit
        ``{"provider": None}`` below is what "nothing set" actually looks like.
        """
        team = _team({"provider": None, "capability": None})
        agent = _agent("writer")
        worker = WorkerRef(agent_id="vaultspec-writer")
        r = resolve_role_assignment(worker, agent, team, None)
        assert r.provider is None
        assert r.provider_source == AssignmentSource.UNDECLARED
        assert r.capability is None
        assert r.capability_source == AssignmentSource.UNDECLARED
        assert r.model_name == ""
        # The absence travels as the one signal every consumer already reads.
        assert r.resolution_error is not None
        assert "no provider is declared" in r.resolution_error

    def test_bundled_adr_research_declares_no_provider_for_any_role(self) -> None:
        """The shipped authoring preset resolves every role to no lane.

        Three tests stood here: one asserting the team default put every role on
        claude, and two asserting the shape of the ``fast`` and provider-axis
        profiles. All three encoded provider/model policy living in a product
        preset, which the catalog contract removes; the profiles they read no
        longer exist.

        What replaces them is the same sweep inverted. Every declared worker is
        still enumerated - so a role vanishing from the preset still fails here -
        but each must now resolve to an absence carrying an honest reason rather
        than to a lane the preset picked.
        """
        team = load_team_config("vaultspec-adr-research")
        assignment = resolve_effective_assignment(team, "team-defaults")
        by_agent = {r.agent_id: r for r in assignment.roles}
        assert set(by_agent) == {
            "vaultspec-researcher",
            "vaultspec-synthesist",
            "vaultspec-adr-author",
            "vaultspec-plan-author",
            "vaultspec-doc-reviewer",
        }
        for agent_id, role in by_agent.items():
            assert role.provider is None, f"{agent_id} still names {role.provider}"
            assert role.capability is None, agent_id
            assert role.provider_source == AssignmentSource.UNDECLARED, agent_id
            assert role.model_name == "", agent_id
            assert role.resolution_error is not None, agent_id

    def test_the_bundled_preset_serves_only_the_implicit_profile(self) -> None:
        """No provider-axis profile survives on the shipped preset."""
        team = load_team_config("vaultspec-adr-research")
        assert set(team.effective_profiles()) == {"team-defaults"}

    def test_unknown_profile_raises_config_error(self) -> None:
        team = load_team_config("vaultspec-adr-research")
        with pytest.raises(ConfigError, match="Unknown model profile 'ghost'"):
            resolve_effective_assignment(team, "ghost")


class TestReadiness:
    def test_mock_is_always_ready(self) -> None:
        r = probe_provider_readiness(Provider.MOCK)
        assert r.ready is True
        assert r.reason is None

    def test_deterministic_is_always_ready(self) -> None:
        # The in-process research_adr acceptance provider (Provider.DETERMINISTIC)
        # needs no credential and no launch command, so the readiness
        # gate must report it runnable - without this the run-start eligibility
        # 422s "unsupported provider deterministic" and the deterministic
        # acceptance lanes cannot start (proven live).
        r = probe_provider_readiness(Provider.DETERMINISTIC)
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

    def test_zai_readiness_reason_is_safe_and_credential_gated(self) -> None:
        """Z.ai readiness gates on the auth token and never leaks it.

        With no token configured the verdict is not-ready with the safe,
        secret-free reason; with a token it proceeds to command resolvability.
        Either way the reason is credential-free.
        """
        token = (settings.zai_auth_token or "").strip()
        r = probe_provider_readiness(Provider.ZAI)
        assert r.provider == Provider.ZAI
        if not token:
            assert r.ready is False
            assert r.reason == "no Z.ai auth token configured"
        elif r.reason is not None:
            assert token not in r.reason

    def test_kimi_persisted_config_mode_reaches_command_readiness(self) -> None:
        """No temporary definition leaves Kimi's persisted-config mode eligible."""
        import shutil

        key = (
            settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else ""
        ).strip()
        r = probe_provider_readiness(Provider.KIMI)
        assert r.provider == Provider.KIMI
        if (
            not key
            and not settings.kimi_base_url
            and not settings.kimi_temporary_model_name
        ):
            assert r.ready is (shutil.which("kimi") is not None)
            if r.ready:
                assert r.reason is None
        if key and r.reason is not None:
            assert key not in r.reason

    def test_codex_command_readiness_uses_public_probe(self) -> None:
        """The public Codex readiness probe delegates to command classification."""
        import shutil

        r = probe_provider_readiness(Provider.CODEX)
        assert r.provider == Provider.CODEX
        if shutil.which("codex") is not None:
            assert r.ready is True
        else:
            assert r.ready is False
            # Path-free by construction; no secret and no filesystem path.
            assert "sk-" not in (r.reason or "")


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
        assert any("production acceptance gate" in reason for reason in elig.reasons)

    def test_eligible_fallback_keeps_role_eligible(self) -> None:
        """A not-ready primary with a ready declared fallback stays eligible."""
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(
                Provider.CLAUDE, False, "no authenticated Claude CLI session found"
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

    def test_incomplete_harness_makes_profile_ineligible(self) -> None:
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(Provider.CLAUDE, True),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=True,
            acceptance_gate_passed=True,
            harness=HarnessReadiness(
                ready=False, reasons=["required templates missing: adr, plan"]
            ),
        )
        assert elig.eligible is False
        assert any("agent harness incomplete" in r for r in elig.reasons)
        assert any("templates missing" in r for r in elig.reasons)

    def test_ready_harness_leaves_profile_eligible(self) -> None:
        readiness = {
            Provider.MOCK: ProviderReadiness(Provider.MOCK, True),
            Provider.CLAUDE: ProviderReadiness(Provider.CLAUDE, True),
        }
        elig = evaluate_profile_eligibility(
            _mock_assignment(),
            readiness=readiness,
            engine_reachable=True,
            acceptance_gate_passed=True,
            harness=HarnessReadiness(ready=True),
        )
        assert elig.eligible is True
        assert elig.reasons == []

    def test_omitted_harness_is_not_composed(self) -> None:
        """A ``None`` harness contributes no reason (non-authoring/unprobed caller)."""
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
        assert not any("harness" in r for r in elig.reasons)


class TestFreeze:
    def test_freeze_produces_compiler_map_and_stable_digest(self) -> None:
        team = _legacy_team()
        assignment = resolve_effective_assignment(team, "fast")
        frozen = freeze_assignment(assignment)
        assert frozen.profile_id == "fast"
        assert frozen.digest  # non-empty sha256
        # The compiler map is a complete frozen execution assignment per role.
        cmap = frozen.compiler_map()
        r = cmap["vaultspec-researcher"]
        assert r["provider"] == "claude"
        assert r["capability"] == "low"
        # Legacy freeze carries no external model name; see the note in
        # ``test_no_overlay_matches_historical_chain``. The digest below is the
        # point of this test and is unaffected.
        assert r["model_name"] == ""
        assert "fallback" in r
        # The disclosure roles carry role_id + model_name + source too.
        assert frozen.roles["vaultspec-researcher"]["role_id"] == "researcher"
        assert frozen.roles["vaultspec-researcher"]["source"] == "profile"

    def test_digest_is_deterministic_and_profile_sensitive(self) -> None:
        team = _legacy_team()
        d_default = freeze_assignment(
            resolve_effective_assignment(team, "team-defaults")
        ).digest
        d_default2 = freeze_assignment(
            resolve_effective_assignment(team, "team-defaults")
        ).digest
        d_fast = freeze_assignment(resolve_effective_assignment(team, "fast")).digest
        assert d_default == d_default2  # deterministic
        assert d_default != d_fast  # a different profile changes the digest

    def test_frozen_round_trips_through_record(self) -> None:
        team = _legacy_team()
        frozen = freeze_assignment(resolve_effective_assignment(team, "fast"))
        record = frozen.to_record()
        restored = frozen_from_record(record)
        assert restored is not None
        assert restored.profile_id == frozen.profile_id
        assert restored.digest == frozen.digest
        assert restored.compiler_map() == frozen.compiler_map()

    def test_frozen_from_bad_record_is_none(self) -> None:
        assert frozen_from_record(None) is None
        assert frozen_from_record({}) is None
        assert frozen_from_record({"profile_id": "x"}) is None
        assert frozen_from_record("garbage") is None
        assert (
            frozen_from_record({"profile_id": "x", "digest": "digest", "roles": []})
            is None
        )
        assert (
            frozen_from_record(
                {
                    "profile_id": "x",
                    "digest": "digest",
                    "roles": {"agent": {"provider": object()}},
                }
            )
            is None
        )
