"""Regression coverage for current lane-admission proof declarations."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from ...graph.enums import Provider
from ...thread.errors import ConfigError
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


def test_every_proven_lane_pairs_with_a_launcher_admission_entry() -> None:
    """A recorded proof without a launcher check would serve an unchecked binary.

    Served eligibility is proof AND the admitted binary identity, so the pairing
    between a lane's proof and the factory entry that measures its resolved
    launcher is itself an invariant: a lane added to the declaration without one
    is refused by :func:`served_lane_eligible` rather than served on the proof
    alone, and this is where that is stated.
    """
    for lane in PROVEN_TURN_LANES:
        assert _launcher_admission(lane) is not None, lane
    for lane in Provider:
        if lane not in PROVEN_TURN_LANES:
            assert _launcher_admission(lane) is None, lane


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
