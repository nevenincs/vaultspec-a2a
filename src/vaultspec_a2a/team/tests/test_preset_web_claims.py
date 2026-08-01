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


def test_at_least_one_shipped_preset_exercises_the_proven_branch() -> None:
    """Some served description actually claims the capability.

    Without this, the guard above stays green forever by the trivial route of no
    description ever claiming anything - which would make it a test of nothing on
    the day the claim was finally added.
    """
    claiming = [
        f"{preset_id} {label}"
        for preset_id in discover_team_preset_ids()
        for label, text, _ in _profile_surfaces(load_team_config(preset_id))
        if _claims_online_research(text)
    ]
    assert claiming, (
        "no shipped preset description claims online research, so the guard above "
        "is passing vacuously. A lane is proven; the profile that runs research on "
        "it should say so."
    )
