"""Regression coverage for current lane-admission proof declarations."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from ...graph.enums import Provider
from ...thread.errors import ConfigError
from ..lane_admission import (
    PROVEN_CATALOG_TURN_LANES,
    PROVEN_TURN_LANES,
    PROVEN_WEB_LANES,
    LaneProof,
    WebLaneProof,
    _lane_of,
    _require_web_proof_implies_turn_proof,
    is_catalog_lane_admissible,
    lane_proof_accepts_version,
)
from ..provider_catalog import ProviderCatalogKey

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
