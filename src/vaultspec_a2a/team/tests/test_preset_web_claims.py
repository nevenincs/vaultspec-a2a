"""A served preset may claim online research only where a lane has proven it.

The sibling guard in ``test_persona_web_claims`` covers the PERSONA surface - what
an agent's own description and system prompt advertise. This one covers the
PRESET surface: the team description and each served profile description, which
is what an operator reads when choosing a lane in the composer.

The two surfaces fail differently and so need separate guards. An over-claiming
persona misleads the model, which then reaches for a tool it does not have. An
over-claiming preset misleads the human, who picks a lane expecting a capability
the run cannot deliver and only discovers it from a thin document.

The rule is the served-profile admission rule applied to descriptions: a claim of
online research is legal only when the role that would perform the research runs
on a lane carrying a completed-retrieval proof. Credential presence and command
resolvability are not sufficient - they say a lane could run, never that it
retrieved.
"""

from __future__ import annotations

import re

import pytest

from ...graph.enums import Provider
from ...providers.lane_admission import PROVEN_WEB_LANES
from ..team_config import discover_team_preset_ids, load_team_config

#: Phrases that assert live web reach to a reader. Deliberately about the
#: CAPABILITY rather than about any tool name: a description naming a specific
#: tool would already be wrong for a different reason, since tool names differ per
#: lane and the persona guard refuses them outright.
_ONLINE_CLAIM_RE = re.compile(
    r"\b(?:live web|online research|search(?:es)? the web|web search|"
    r"reach the live web|retriev\w+ from the web)\b",
    re.IGNORECASE,
)

#: The role whose job is to gather external material. A claim of online research
#: is a claim about what THIS role can do; a profile that runs it on an unproven
#: lane cannot make the claim however its other roles are assigned.
_RESEARCHING_ROLE = "researcher"


def _claims_online_research(text: str) -> bool:
    return bool(_ONLINE_CLAIM_RE.search(text or ""))


def _profile_surfaces(team) -> list[tuple[str, str, str | None]]:
    """Return every served description surface as (label, text, profile id).

    ``profiles`` is a MAPPING of id to profile, not a sequence. Iterating it
    directly yields ids and every description reads as empty, which would make
    this guard pass on any input - the anti-vacuity check below exists because
    that is exactly what happened when this was first written.
    """
    surfaces: list[tuple[str, str, str | None]] = [
        ("team description", team.description or "", None)
    ]
    surfaces.extend(
        (f"profile {profile_id} description", profile.description or "", profile_id)
        for profile_id, profile in (team.profiles or {}).items()
    )
    return surfaces


def _provider_for_researcher(team, profile_id: str | None) -> Provider | None:
    """Return the provider the researching role resolves to under *profile_id*.

    Reads the real preset structures so a profile overlay repointing the role is
    followed exactly as a run would follow it, rather than a restatement of the
    overlay rules that could drift from them.
    """
    overlay: dict[str, object] = {}
    if profile_id is not None:
        profile = (team.profiles or {}).get(profile_id)
        overlay = dict(getattr(profile, "roles", {}) or {}) if profile else {}

    raw = getattr(getattr(team, "defaults", None), "provider", None)
    for agent_id, entry in overlay.items():
        if _RESEARCHING_ROLE in agent_id:
            raw = getattr(entry, "provider", None) or entry or raw
            break

    try:
        return Provider(raw) if raw else None
    except ValueError:
        return None


@pytest.mark.parametrize("preset_id", sorted(discover_team_preset_ids()))
def test_no_served_preset_claims_online_research_on_an_unproven_lane(
    preset_id: str,
) -> None:
    """Every description that claims live web reach runs research on a proven lane.

    Scans the team description and every served profile description. The failure
    this catches is the one the campaign kept finding in other forms: a surface
    asserting a capability because it was planned rather than because it was
    demonstrated.
    """
    team = load_team_config(preset_id)

    for label, text, profile_id in _profile_surfaces(team):
        if not _claims_online_research(text):
            continue
        provider = _provider_for_researcher(team, profile_id)
        assert provider is not None, (
            f"{preset_id} {label} claims online research but the researching role "
            f"resolves to no provider, so the claim cannot be checked at all"
        )
        assert provider in PROVEN_WEB_LANES, (
            f"{preset_id} {label} claims online research while its researching "
            f"role runs on {provider.value}, which carries no completed-retrieval "
            f"proof. Either withdraw the claim or land the lane's live proof "
            f"first - a served description is read by an operator choosing a lane, "
            f"and an unbacked claim is discovered only from a thin document."
        )


def test_the_claim_vocabulary_this_guard_scans_for_is_not_empty() -> None:
    """The scan matches real claim phrasings, so a green run is not vacuous.

    A guard whose pattern matches nothing passes on every input and proves
    nothing. This pins the pattern against phrasings a description would
    plausibly use, including the one shipped today.
    """
    assert _claims_online_research("Researchers on this profile reach the live web")
    assert _claims_online_research("performs online research before authoring")
    assert _claims_online_research("the researcher searches the web for sources")
    assert not _claims_online_research(
        "reads codebase files and vault documents, and cites them by locator"
    )


def test_no_shipped_preset_claims_online_research_at_all() -> None:
    """The rule in its strengthened form: a preset may not make the claim.

    This replaces an anti-vacuity guard that REQUIRED some shipped description to
    claim online research, on the reasoning that a guard nothing exercises proves
    nothing. That reasoning was sound while a preset could name its own lane: the
    only claim in the tree was a provider-axis profile description, and the claim
    was legal because that profile pinned research to a lane carrying a
    completed-retrieval proof.

    Product presets now carry no provider policy, so no preset knows which lane
    its researcher will run on - the user selects it at run start from the served
    catalog. A description that promised online research would therefore be
    promising something the preset cannot know, whichever lane is later chosen.
    The admissible number of such claims is zero, and that is what is asserted.

    This is not a relaxation. The old guard permitted a claim on a proven lane;
    this permits none, so every state it rejected is still rejected. The
    capability claim itself has not been abandoned - it moved to where the lane
    actually lives, and ``PROVEN_WEB_LANES`` still gates it there.
    """
    claiming = [
        f"{preset_id} {label}"
        for preset_id in discover_team_preset_ids()
        for label, text, _ in _profile_surfaces(load_team_config(preset_id))
        if _claims_online_research(text)
    ]
    assert claiming == [], (
        f"shipped preset description(s) {claiming} claim online research. A preset "
        "carries no provider policy, so it cannot know which lane its researcher "
        "runs on and cannot back the claim. Make the claim where the lane is "
        "chosen, not where the topology is declared."
    )


def test_the_preset_surface_sweep_actually_reaches_the_shipped_presets() -> None:
    """The zero above is a real zero, not an empty sweep.

    An assertion that a derived list is empty passes trivially when the
    derivation collects nothing, which would make the guard above meaningless the
    day a claim was re-added. So the sweep's reach is pinned independently: it
    must load the real presets and actually read description text from them.
    """
    surfaces = [
        (preset_id, label, text)
        for preset_id in discover_team_preset_ids()
        for label, text, _ in _profile_surfaces(load_team_config(preset_id))
    ]
    assert len(surfaces) >= 10, surfaces
    assert any(preset_id == "vaultspec-adr-research" for preset_id, _, _ in surfaces)
    assert any(text.strip() for _, _, text in surfaces), (
        "every scanned surface is empty, so the claim scan reads nothing"
    )
