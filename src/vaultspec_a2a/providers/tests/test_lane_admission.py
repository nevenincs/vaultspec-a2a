"""Tests for the per-lane capability gates: completed-turn and completed-web proof.

Real configuration only: real ``TeamConfig`` objects, the real bundled presets,
the real resolver, and the real eligibility service. Provider readiness is
supplied through ``evaluate_profile_eligibility``'s injectable ``readiness``
argument - a first-class API parameter, not a patch of the probe - which is what
lets these tests state the sharp claim the rule needs: a lane whose credential
resolves and whose command is present is STILL refused without completed-turn
proof.

The web-grounding declaration is empty at landing, so its tests assert the gate is
dark and - more importantly - that the checks guarding it are ones that can fail:
the citation checker is driven against real rotted citations, the coherence
implication against real incoherent pairs, and lane resolution against every enum
member, so nothing here is green merely because the mapping has no entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from ...graph.enums import Provider
from ...team.team_config import (
    TeamConfig,
    discover_team_preset_ids,
    load_team_config,
)
from ...thread.errors import ConfigError
from ..lane_admission import (
    IN_PROCESS_LANES,
    PROVEN_TURN_LANES,
    PROVEN_WEB_LANES,
    LaneProof,
    WebLaneProof,
    _lane_of,
    _require_web_proof_implies_turn_proof,
    is_lane_admissible,
    is_web_lane_proven,
    lane_admission_reason,
    unproven_lanes_in,
    web_tool_names_for,
)
from ..model_profiles import (
    ProviderReadiness,
    evaluate_profile_eligibility,
    resolve_effective_assignment,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_THIS_MODULE = "src/vaultspec_a2a/providers/tests/test_lane_admission.py"

# Lanes the audit found serving (or servable) without a completed turn. Kimi is
# the one that actually shipped into a served profile on handshake-only evidence.
UNPROVEN_LANES = (Provider.KIMI, Provider.GEMINI, Provider.OPENAI, Provider.ZHIPU)

# The shipped violation this gate was built to expose, named exactly. The
# `vaultspec-adr-research` preset ships two kimi-lane profiles and kimi is
# handshake-proven only, so these roles name a lane the backend has never
# completed work on. They are declared rather than tolerated: the sweep below
# pins the offence set to this literal, so it still fails on a new offence, and
# fails again when these are resolved.
KNOWN_UNPROVEN_PRESET_LANES = tuple(
    f"vaultspec-adr-research/{profile}/{agent} names unproven lane kimi"
    for profile, agents in (
        (
            "kimi",
            (
                "vaultspec-adr-author",
                "vaultspec-plan-author",
                "vaultspec-researcher",
                "vaultspec-synthesist",
            ),
        ),
        (
            "kimi-all",
            (
                "vaultspec-adr-author",
                "vaultspec-doc-reviewer",
                "vaultspec-plan-author",
                "vaultspec-researcher",
                "vaultspec-synthesist",
            ),
        ),
    )
    for agent in agents
)


def _team_with_profile(
    profile_provider: Provider | None = None,
    *,
    worker_provider: Provider | None = None,
    fallback: list[Provider] | None = None,
) -> TeamConfig:
    """A real one-worker team whose ``candidate`` profile overlays a lane.

    The worker is a real bundled agent so ``resolve_effective_assignment`` loads
    a real agent TOML and the assignment resolves for real - no synthetic role,
    no resolution error standing in for the verdict under test.
    ``worker_provider`` names the lane one precedence layer below the profile, in
    the ``[[team.workers]]`` override, for asserting the gate follows the resolved
    lane rather than the layer that named it.
    """
    roles: dict[str, object] = {}
    overlay: dict[str, object] = {}
    if profile_provider is not None:
        overlay["provider"] = profile_provider.value
    if fallback is not None:
        overlay["provider_fallback"] = [p.value for p in fallback]
    if overlay:
        roles["vaultspec-researcher"] = overlay
    worker: dict[str, object] = {"agent_id": "vaultspec-researcher"}
    if worker_provider is not None:
        worker["model"] = {"provider": worker_provider.value}
    return TeamConfig.model_validate(
        {
            "id": "admission-fixture",
            "display_name": "Admission fixture",
            "defaults": {"provider": Provider.CLAUDE.value, "capability": "mid"},
            "topology": {"type": "star"},
            "workers": [worker],
            "profiles": {"candidate": {"roles": roles}},
        }
    )


def _citation_problem(test_node: str) -> str | None:
    """Return why *test_node* fails to resolve on disk, or ``None`` when it does.

    The citation is the whole value of a proof entry - it is what a reviewer
    re-runs to re-check the claim - so both halves are resolved: the file must
    exist and the named test function must be defined in it. A citation that has
    rotted away is an admission nobody can check.
    """
    module_path, _, node = test_node.partition("::")
    test_file = _REPO_ROOT / module_path
    if not test_file.is_file():
        return f"missing proof file: {module_path}"
    function_name = node.split("[")[0]
    if f"def {function_name}(" not in test_file.read_text(encoding="utf-8"):
        return f"missing proof test: {node}"
    return None


def _eligibility_of(team: TeamConfig, profile_id: str, ready: list[Provider]):
    """Resolve *profile_id* and rate it with every lane in *ready* fully ready.

    Engine reachability, the acceptance gate, and the harness are all satisfied,
    so the only term that can refuse the profile is the one under test.
    """
    assignment = resolve_effective_assignment(team, profile_id)
    return evaluate_profile_eligibility(
        assignment,
        readiness={p: ProviderReadiness(p, True) for p in ready},
        engine_reachable=True,
        acceptance_gate_passed=True,
    )


class TestDeclaration:
    def test_unlisted_lane_is_denied_by_default(self) -> None:
        """Absence from the declaration is a refusal, not a fall-through.

        This is the property that makes a newly added provider safe from birth:
        it is unproven until a human records its proof.
        """
        for provider in UNPROVEN_LANES:
            assert provider not in PROVEN_TURN_LANES
            assert is_lane_admissible(provider) is False

    def test_declared_lanes_are_admissible(self) -> None:
        assert set(PROVEN_TURN_LANES) == {
            Provider.CLAUDE,
            Provider.CODEX,
            Provider.ZAI,
        }
        for provider in (*PROVEN_TURN_LANES, *IN_PROCESS_LANES):
            assert is_lane_admissible(provider) is True

    def test_every_provider_is_classified(self) -> None:
        """No enum member is unaccounted for: it is proven, in-process, or refused."""
        for provider in Provider:
            admissible = is_lane_admissible(provider)
            declared = provider in PROVEN_TURN_LANES or provider in IN_PROCESS_LANES
            assert admissible is declared

    def test_each_proven_lane_cites_a_live_test_that_exists(self) -> None:
        """Every admission claim points at a real, re-runnable proof."""
        for provider, proof in PROVEN_TURN_LANES.items():
            problem = _citation_problem(proof.test)
            assert problem is None, f"{provider.value} cites a {problem}"
            assert proof.proves.strip()

    def test_reason_names_the_provider_and_clears_for_admissible_lanes(self) -> None:
        reason = lane_admission_reason(Provider.KIMI)
        assert reason is not None
        assert "kimi" in reason
        assert "completed-turn proof" in reason
        assert lane_admission_reason(Provider.CLAUDE) is None

    def test_unproven_lanes_in_reports_every_offender_deduped_in_order(self) -> None:
        found = unproven_lanes_in(
            [
                Provider.CLAUDE,
                Provider.KIMI,
                Provider.MOCK,
                Provider.GEMINI,
                Provider.KIMI,
            ]
        )
        assert found == [Provider.KIMI, Provider.GEMINI]


class TestCitationResolution:
    """The citation checker itself, so the guard is never vacuously green.

    :data:`PROVEN_WEB_LANES` is empty at landing, so a loop over its entries
    cannot fail today; these cases prove the check the loop applies is one that
    can, and would, catch a rotted citation the day an entry lands.
    """

    def test_a_citation_naming_no_file_is_reported(self) -> None:
        assert (
            _citation_problem("src/vaultspec_a2a/providers/tests/test_nothing.py::t")
            == "missing proof file: src/vaultspec_a2a/providers/tests/test_nothing.py"
        )

    def test_a_citation_naming_an_absent_test_in_a_real_file_is_reported(self) -> None:
        problem = _citation_problem(f"{_THIS_MODULE}::test_no_such_test")
        assert problem == "missing proof test: test_no_such_test"

    def test_a_resolvable_citation_reports_nothing(self) -> None:
        node = f"{_THIS_MODULE}::test_a_resolvable_citation_reports_nothing"
        assert _citation_problem(node) is None


class TestWebDeclaration:
    """The web-grounding activation gate: dark by default, lit only by proof."""

    def test_only_a_lane_with_recorded_retrieval_proof_is_activated(self) -> None:
        """Activation follows the declaration exactly - no lane rides along.

        The declaration landed empty and now carries the lanes whose live proofs
        have landed, so this states which ones and asserts every other member of
        the enum is still dark. That second half is what stops the gate degrading
        into a formality as lanes are added: a proof recorded for one lane must
        activate that lane alone.
        """
        assert set(PROVEN_WEB_LANES) == {Provider.CODEX, Provider.CLAUDE}
        for provider in Provider:
            expected = provider in PROVEN_WEB_LANES
            assert is_web_lane_proven(provider) is expected

    def test_a_configured_reach_activates_no_allowlist_name(self) -> None:
        """The proven lane composes no tool name, because it has none to compose.

        Its web reach is configuration - the posture written into its per-run
        config home - not a built-in the allowlist can carry, so the honest
        declaration records no names and composition adds nothing. A name
        appearing here would be a tool the proof never exercised.
        """
        assert web_tool_names_for(Provider.CODEX) == ()
        for provider in Provider:
            if provider not in PROVEN_WEB_LANES:
                assert web_tool_names_for(provider) == ()

    def test_a_permitted_reach_activates_exactly_the_names_its_proof_exercised(
        self,
    ) -> None:
        """A lane delivering reach through built-ins composes those built-ins only.

        The counterpart shape to the configured lane above, and the reason
        ``tool_names`` rides the proof rather than a lane-blind constant: the
        claude proof fetched named URLs and never searched, so its declaration
        carries the fetch built-in alone. A search name appearing here would be a
        tool activated on another tool's evidence, which is the substitution this
        whole declaration exists to refuse.
        """
        assert web_tool_names_for(Provider.CLAUDE) == ("WebFetch",)

    def test_an_unidentified_lane_denies_instead_of_raising(self) -> None:
        """A model that declared no lane, or one nobody has heard of, is unproven.

        Composition consults this gate on every autonomous turn, so an unresolvable
        provider value must land on deny rather than raise at the spawn seam.
        """
        for value in (None, "", "not-a-provider", "Claude", " claude"):
            assert is_web_lane_proven(value) is False
            assert web_tool_names_for(value) == ()

    def test_a_lane_string_resolves_to_its_enum_member(self) -> None:
        """The gate is consulted with the bounded string an ACP model carries.

        If resolution silently failed, every lane would read as unidentified and a
        recorded proof could never activate anything - a dead capability that no
        empty-set assertion above would ever catch.
        """
        for provider in Provider:
            assert _lane_of(provider.value) is provider
            assert _lane_of(provider) is provider
        assert _lane_of("not-a-provider") is None
        assert _lane_of(None) is None

    def test_web_proof_without_turn_proof_is_refused(self) -> None:
        """The implication that keeps the two declarations from disagreeing.

        Driven against the real validator with real record types: a lane activated
        for web while unservable for turns is refused, naming the lane.
        """
        offending = {
            Provider.KIMI: WebLaneProof(
                test="src/vaultspec_a2a/providers/tests/test_lane_admission.py::x",
                proves="nothing - this lane has no completed turn",
            )
        }
        with pytest.raises(ConfigError) as excinfo:
            _require_web_proof_implies_turn_proof(offending, PROVEN_TURN_LANES)
        assert "kimi" in str(excinfo.value)
        assert "completed-turn proof" in str(excinfo.value)

    def test_an_in_process_lane_can_never_be_web_proven(self) -> None:
        """Turn-admissible is not enough: the in-process lanes hold no turn proof.

        They spawn no CLI, so there is nothing there to retrieve with, and the
        implication rejects them even though ``is_lane_admissible`` admits them.
        """
        for lane in IN_PROCESS_LANES:
            assert is_lane_admissible(lane) is True
            with pytest.raises(ConfigError):
                _require_web_proof_implies_turn_proof(
                    {lane: WebLaneProof(test="t::t", proves="p")}, PROVEN_TURN_LANES
                )

    def test_a_turn_proven_lane_is_accepted_by_the_implication(self) -> None:
        """The guard refuses incoherent pairs, not every pair."""
        for lane in PROVEN_TURN_LANES:
            _require_web_proof_implies_turn_proof(
                {lane: WebLaneProof(test="t::t", proves="p")}, PROVEN_TURN_LANES
            )

    def test_each_web_proven_lane_cites_a_live_test_that_exists(self) -> None:
        for provider, proof in PROVEN_WEB_LANES.items():
            problem = _citation_problem(proof.test)
            assert problem is None, f"{provider.value} cites a {problem}"
            assert proof.proves.strip()

    def test_a_proof_activates_no_tool_name_unless_it_records_one(self) -> None:
        """An omitted ``tool_names`` is empty, never a defaulted web tool set.

        A lane whose web reach is configured rather than permitted is proven with
        no names at all, so the default must add nothing to any allowlist.
        """
        assert WebLaneProof(test="t::t", proves="p").tool_names == ()
        assert WebLaneProof(
            test="t::t", proves="p", tool_names=("WebSearch",)
        ).tool_names == ("WebSearch",)

    def test_the_declaration_cannot_be_extended_at_runtime(self) -> None:
        """Membership IS the declaration, so an importer must not be able to add.

        A plain dict here would let any module activate a lane with one assignment,
        which is the hand-edited-declaration rule defeated at import time.
        """
        with pytest.raises(TypeError):
            cast("dict[Provider, WebLaneProof]", PROVEN_WEB_LANES)[Provider.KIMI] = (
                WebLaneProof(test="t::t", proves="p")
            )
        with pytest.raises(TypeError):
            cast("dict[Provider, LaneProof]", PROVEN_TURN_LANES)[Provider.KIMI] = (
                LaneProof(test="t::t", proves="p")
            )


class TestServedEligibility:
    @pytest.mark.parametrize("provider", UNPROVEN_LANES)
    def test_unproven_lane_is_refused_though_its_credential_is_ready(
        self, provider: Provider
    ) -> None:
        """The gate's whole point: readiness is necessary, never sufficient.

        The lane is declared fully ready, which is the exact state the old
        credential-only gate would have served the profile in.
        """
        team = _team_with_profile(provider)
        elig = _eligibility_of(team, "candidate", [provider, Provider.CLAUDE])

        assert elig.eligible is False
        assert any(provider.value in reason for reason in elig.reasons), elig.reasons
        assert any("completed-turn proof" in reason for reason in elig.reasons)
        refused = [r for r in elig.roles if not r.eligible]
        assert [r.agent_id for r in refused] == ["vaultspec-researcher"]
        assert provider.value in (refused[0].reason or "")

    @pytest.mark.parametrize("provider", sorted(PROVEN_TURN_LANES, key=str))
    def test_proven_lane_still_resolves_and_stays_eligible(
        self, provider: Provider
    ) -> None:
        """The gate refuses unproven lanes, not everything."""
        team = _team_with_profile(provider)
        elig = _eligibility_of(team, "candidate", [provider, Provider.CLAUDE])

        assert elig.eligible is True, elig.reasons
        assert elig.reasons == []
        assert all(r.eligible for r in elig.roles)

    def test_unproven_declared_fallback_refuses_the_role(self) -> None:
        """A fallback is a lane the run can actually degrade onto, so it is gated.

        The primary is proven and ready here; only the fallback offends, and the
        role is still refused - otherwise the unproven lane would complete its
        first real turn mid-run, after every gate had passed.
        """
        team = _team_with_profile(Provider.CLAUDE, fallback=[Provider.KIMI])
        elig = _eligibility_of(team, "candidate", [Provider.CLAUDE, Provider.KIMI])

        assert elig.eligible is False
        assert any("declared fallback" in reason for reason in elig.reasons)
        assert any("kimi" in reason for reason in elig.reasons)

    def test_proven_fallback_does_not_launder_an_unproven_primary(self) -> None:
        """A healthy fallback must not buy admission for the lane it backs up."""
        team = _team_with_profile(Provider.KIMI, fallback=[Provider.CLAUDE])
        elig = _eligibility_of(team, "candidate", [Provider.CLAUDE, Provider.KIMI])

        assert elig.eligible is False
        assert any("primary" in reason and "kimi" in reason for reason in elig.reasons)

    def test_refusal_survives_every_other_term_being_satisfied(self) -> None:
        """No other passing term can outvote admission; the refusal stands alone."""
        team = _team_with_profile(Provider.KIMI)
        elig = _eligibility_of(team, "candidate", list(Provider))

        assert elig.eligible is False
        assert len(elig.reasons) == 1
        assert "kimi" in elig.reasons[0]

    def test_a_lane_reaching_a_role_below_the_profile_layer_is_gated_too(self) -> None:
        """Admission follows the RESOLVED lane, not the layer that named it.

        Here no profile overlay exists at all and the unproven lane arrives from
        the worker override one layer down; the served verdict must be identical,
        or the gate would be bypassable by moving one line along the precedence
        chain. (The layer below that, ``[team.defaults]``, cannot carry this case:
        the bundled researcher pins its own provider, so a team default never
        reaches the role at all.)
        """
        team = _team_with_profile(None, worker_provider=Provider.OPENAI)
        elig = _eligibility_of(team, "candidate", list(Provider))

        assert elig.eligible is False
        assert any("openai" in reason for reason in elig.reasons)


class TestBundledPresetConformance:
    """Every profile this backend ships must name only admissible lanes.

    This is the guard against the shipped violation returning: re-adding a
    handshake-only lane to any bundled preset fails here, at the composition the
    product actually serves.
    """

    def test_the_shipped_unproven_lanes_are_exactly_the_known_ones(self) -> None:
        """The sweep is pinned to the violation that exists, not to zero.

        Exact equality in both directions is the point: a NEW preset naming an
        unproven lane fails here, and so does the day these stop offending -
        whether kimi earns its completed-turn proof or the profiles are dropped,
        whoever does it must come back and shrink this literal. A substring
        tolerance would have silently absorbed both.
        """
        loadable: list[str] = []
        unloadable: list[str] = []
        offences: list[str] = []

        for preset_id in sorted(discover_team_preset_ids()):
            try:
                team = load_team_config(preset_id)
            except (ConfigError, ValueError):
                unloadable.append(preset_id)
                continue
            loadable.append(preset_id)
            for profile_id in sorted(team.effective_profiles()):
                assignment = resolve_effective_assignment(team, profile_id)
                for role in assignment.roles:
                    assert role.resolution_error is None, (
                        f"{preset_id}/{profile_id}/{role.agent_id} does not resolve: "
                        f"{role.resolution_error}"
                    )
                    unproven = unproven_lanes_in(
                        [role.provider, *role.fallback_providers]
                    )
                    offences.extend(
                        f"{preset_id}/{profile_id}/{role.agent_id} names "
                        f"unproven lane {p.value}"
                        for p in unproven
                    )

        # Guards against a vacuous pass: the sweep must actually have loaded the
        # shipped presets. Every bundled preset loads today - `mock-invalid` is
        # invalid at RUNTIME (it drives a LangGraph InvalidUpdateError), not at
        # config load - so a change that broke a preset's config would otherwise
        # hide here as a shrinking offence list.
        assert unloadable == [], unloadable
        assert "vaultspec-adr-research" in loadable
        assert len(loadable) >= 10, loadable
        assert sorted(offences) == sorted(KNOWN_UNPROVEN_PRESET_LANES), offences

    @pytest.mark.parametrize("profile_id", ("kimi", "kimi-all"))
    def test_the_known_offending_profiles_are_refused_by_the_served_gate(
        self, profile_id: str
    ) -> None:
        """The shipped violation is CONTAINED, which is what the gate is for.

        The declaration above catalogues the offence; this asserts the product
        does not serve it. Every lane is declared fully ready, so the only term
        that can refuse the profile is admission - the exact state in which the
        old credential-only gate served these profiles.
        """
        team = load_team_config("vaultspec-adr-research")
        elig = _eligibility_of(team, profile_id, list(Provider))

        assert elig.eligible is False
        assert any("kimi" in reason for reason in elig.reasons), elig.reasons
        assert any("completed-turn proof" in reason for reason in elig.reasons)
