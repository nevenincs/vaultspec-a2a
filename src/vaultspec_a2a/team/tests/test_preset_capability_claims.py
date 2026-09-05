"""Topology-only presets cannot promise lane-dependent web capability."""

import re

from ..team_config import discover_team_preset_ids, load_team_config

_ONLINE = re.compile(
    r"\b(?:live web|online research|search(?:es)? the web|web search|"
    r"reach the live web|retriev\w+ from the web)\b",
    re.IGNORECASE,
)


def test_topology_only_presets_make_no_unearned_online_claims() -> None:
    surfaces = [
        (preset_id, load_team_config(preset_id).description or "")
        for preset_id in sorted(discover_team_preset_ids())
    ]
    assert len(surfaces) >= 10
    assert any(preset_id == "vaultspec-adr-research" for preset_id, _ in surfaces)
    assert any(text.strip() for _, text in surfaces)
    assert [preset_id for preset_id, text in surfaces if _ONLINE.search(text)] == []


def test_online_claim_vocabulary_is_nonempty() -> None:
    assert _ONLINE.search("Researchers reach the live web")
    assert _ONLINE.search("performs online research")
    assert not _ONLINE.search("reads codebase files and cites them")
