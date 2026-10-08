"""Regression coverage for current lane-admission proof declarations."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from ...graph.enums import Provider
from ...thread.errors import ConfigError
from ..cli_resolution import ProviderRuntimeUnavailableReason
from ..execution_modes import ACP_BACKEND_LANES
from ..in_process_catalog import in_process_catalog_key
from ..lane_admission import (
    PROVEN_CATALOG_TURN_LANES,
    PROVEN_TURN_LANES,
    PROVEN_WEB_LANES,
    LaneProof,
    WebLaneProof,
    _lane_of,
    _launcher_admission,
    _require_web_proof_implies_turn_proof,
    is_catalog_lane_admissible,
    lane_proof_accepts_version,
    served_lane_eligible,
)
from ..lane_registry import registered_lanes
from ..provider_catalog import ProviderCatalogKey
from ..provider_readiness import probe_provider_readiness

_ROOT = Path(__file__).resolve().parents[4]
_HERE = "src/vaultspec_a2a/providers/tests/test_lane_admission_current.py"


def _citation_problem(node_id: str) -> str | None:
    module, _, node = node_id.partition("::")
    path = _ROOT / module
    if not path.is_file():
        return f"missing proof file: {module}"
    function = node.split("[")[0]
    if f"def {function}(" not in path.read_text(encoding="utf-8"):
        return f"missing proof test: {node}"
    return None


def test_live_and_rotten_proof_citations_are_discriminated() -> None:
    for proof in (*PROVEN_TURN_LANES.values(), *PROVEN_WEB_LANES.values()):
        assert _citation_problem(proof.test) is None
    assert _citation_problem("src/no-such-proof.py::test_missing") is not None
    assert (
        _citation_problem(f"{_HERE}::test_missing")
        == "missing proof test: test_missing"
    )
    assert (
        _citation_problem(
            f"{_HERE}::test_live_and_rotten_proof_citations_are_discriminated"
        )
        is None
    )


def test_proof_declarations_are_immutable() -> None:
    with pytest.raises(TypeError):
        cast("dict[Provider, LaneProof]", PROVEN_TURN_LANES)[Provider.KIMI] = LaneProof(
            "x", "x", "x", "0.0.1", "0.0.1", "0.1.0"
        )
    with pytest.raises(TypeError):
        cast("dict[Provider, WebLaneProof]", PROVEN_WEB_LANES)[Provider.KIMI] = (
            WebLaneProof("x", "x")
        )


def test_web_proof_requires_turn_proof_and_provider_resolution_is_exact() -> None:
    with pytest.raises(ConfigError, match="completed-turn proof"):
        _require_web_proof_implies_turn_proof(
            {Provider.KIMI: WebLaneProof("x", "x")}, PROVEN_TURN_LANES
        )
    for provider in Provider:
        assert _lane_of(provider.value) is provider
    for invalid in (None, "", "Claude", " claude", "unknown"):
        assert _lane_of(invalid) is None


def test_only_the_reproved_codex_binary_is_declared_for_external_serving() -> None:
    assert set(PROVEN_TURN_LANES) == {Provider.CODEX}
    assert set(PROVEN_WEB_LANES) == {Provider.CODEX}
    assert set(PROVEN_CATALOG_TURN_LANES) == {
        ProviderCatalogKey("codex", "codex-app-server")
    }
    proof = PROVEN_TURN_LANES[Provider.CODEX]
    assert proof.binary == "codex"
    assert proof.proved_version == proof.floor
    major, minor, _patch = map(int, proof.proved_version.split("."))
    assert tuple(map(int, proof.ceiling_exclusive.split("."))) == (major, minor + 1, 0)
    for provider, execution_mode in (
        (Provider.CLAUDE, "claude-agent-acp:node"),
        (Provider.ZAI, "zai-claude-agent-acp:node"),
    ):
        assert provider not in PROVEN_TURN_LANES
        assert not is_catalog_lane_admissible(
            ProviderCatalogKey(provider.value, execution_mode)
        )


def test_proof_range_rejects_unproved_and_malformed_versions() -> None:
    proof = PROVEN_TURN_LANES[Provider.CODEX]
    major, minor, patch = map(int, proof.proved_version.split("."))
    later_patch = f"{major}.{minor}.{patch + 1}"
    if patch:
        previous = f"{major}.{minor}.{patch - 1}"
    elif minor:
        previous = f"{major}.{minor - 1}.0"
    else:
        assert major > 0, "A below-floor control requires a nonzero proved version"
        previous = f"{major - 1}.0.0"
    assert lane_proof_accepts_version(proof, proof.proved_version, "service_path")
    assert lane_proof_accepts_version(proof, later_patch, "service_path")
    assert not lane_proof_accepts_version(
        proof, proof.ceiling_exclusive, "service_path"
    )
    assert not lane_proof_accepts_version(proof, previous, "service_path")
    assert lane_proof_accepts_version(proof, proof.proved_version, "capsule")
    assert not lane_proof_accepts_version(proof, later_patch, "capsule")
    assert not lane_proof_accepts_version(
        proof, f"{proof.proved_version}-dev", "service_path"
    )
    assert not lane_proof_accepts_version(proof, "unknown", "service_path")
    assert not lane_proof_accepts_version(proof, proof.proved_version, "unknown")
    assert not lane_proof_accepts_version(
        replace(proof, ceiling_exclusive=f"{major}.{minor + 2}.0"),
        proof.proved_version,
        "service_path",
    )


def test_every_launcher_backed_lane_pairs_with_a_launcher_admission_entry() -> None:
    """A recorded proof without a launcher check would serve an unchecked binary.

    Served eligibility is proof AND the admitted binary identity, so the pairing
    between a lane's launcher and the factory entry that measures it is itself an
    invariant: a lane added to the proof declaration without a pairing here is
    refused by :func:`served_lane_eligible` rather than served on the proof
    alone, and this is where that is stated.

    The pairing is asked of every lane whose factory launches a CLI (the
    Claude-backed ACP lanes, Codex, Kimi) rather than only the lanes with a
    proof entry TODAY: it is keyed on which lane FAMILY has a checkable
    launcher, not on :data:`PROVEN_TURN_LANES`'s current contents, so Claude's
    or Z.ai's or Kimi's proof can be recorded later without a second edit here
    to actually enforce it. A lane with no CLI launcher at all - a lane this
    process holds, or a plain hosted API with nothing to spawn - has nothing
    for this pairing to check and stays unpaired.
    """
    launcher_backed_lanes = {*ACP_BACKEND_LANES, Provider.CODEX, Provider.KIMI}
    assert PROVEN_TURN_LANES.keys() <= launcher_backed_lanes
    for lane in launcher_backed_lanes:
        assert _launcher_admission(lane) is not None, lane
    for lane in Provider:
        if lane not in launcher_backed_lanes:
            assert _launcher_admission(lane) is None, lane


def test_claude_family_launcher_admission_needs_no_workspace() -> None:
    """The Claude/Z.ai pairing calls the factory's workspace-free binary proof.

    ``_launcher_admission`` runs at served-eligibility time, independent of any
    particular run, so it has no workspace to hand the factory's original
    ``_claude_binary_proof_reason`` (which REQUIRES one). The entry paired here
    must be the public, workspace-free sibling - proven by calling it with zero
    arguments and no workspace in scope at all, which would raise a TypeError
    immediately if the pairing had reverted to the workspace-taking probe.
    Neither lane carries a proof entry yet, so the answer is the same
    ``BINARY_PROOF_MISSING`` the probe gives every unproven lane - the
    assertion that matters is that calling it needs nothing else.
    """
    for lane in (Provider.CLAUDE, Provider.ZAI):
        admission = _launcher_admission(lane)
        assert admission is not None, lane
        assert admission() is ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING


def test_an_unproven_external_lane_is_refused_however_ready_it_is() -> None:
    """Readiness is necessary, not sufficient: no proof means no service.

    Whichever lanes this host happens to have installed and credentialed, an
    external lane absent from the declaration is refused, under either spelling.
    A lane this process HOLDS is the one exception and is asserted separately
    below: it carries no proof because there is no transport to earn one on.
    """
    held = {lane.provider for lane in registered_lanes()}
    for lane in Provider:
        if lane in PROVEN_TURN_LANES or lane in held:
            continue
        assert not served_lane_eligible(lane), lane
        assert not served_lane_eligible(lane.value), lane


def test_a_held_in_process_lane_is_eligible_exactly_as_the_catalog_admits_it() -> None:
    """The execution surface and the catalog surface agree on the held lanes.

    An in-process lane spawns no CLI, so the completed-turn standard cannot
    apply to it and both predicates admit it as a HELD lane instead. Asserting
    the two together is what keeps a lane that is selectable in the catalog from
    being refused capacity at admission.
    """
    for lane in registered_lanes():
        assert served_lane_eligible(lane.provider), lane.provider
        assert is_catalog_lane_admissible(in_process_catalog_key(lane)), lane.provider


def test_an_unidentifiable_lane_is_refused_rather_than_raised_on() -> None:
    for unknown in (None, "", "Codex", " codex", "unknown"):
        assert not served_lane_eligible(unknown)


def test_a_proven_lane_is_served_only_while_readiness_and_its_binary_agree() -> None:
    """The three terms are conjunctive, measured against this host as it is.

    The host supplies the launcher, so the assertion is the RELATION between the
    three verdicts rather than a fixed answer: a lane is served exactly when it
    carries proof, answers ready, and its resolved launcher reports a version the
    proof admits. A host missing the CLI exercises the refusing direction and a
    host with it exercises the admitting one.
    """
    for lane, proof in PROVEN_TURN_LANES.items():
        admission = _launcher_admission(lane)
        assert admission is not None
        ready = probe_provider_readiness(lane).ready
        binary_admitted = admission() is None
        assert served_lane_eligible(lane) is (ready and binary_admitted), (
            lane,
            proof.proved_version,
        )
