"""Regression coverage for current lane-admission proof declarations."""

from pathlib import Path
from typing import cast

import pytest

from ...graph.enums import Provider
from ...thread.errors import ConfigError
from ..lane_admission import (
    PROVEN_TURN_LANES,
    PROVEN_WEB_LANES,
    LaneProof,
    WebLaneProof,
    _lane_of,
    _require_web_proof_implies_turn_proof,
)

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
            "x", "x"
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
