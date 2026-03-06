"""Tests for src/vaultspec_a2a/core/phase.py — infer_phase_from_vault_index."""

import pytest

from ..phase import PHASE_ORDER, infer_phase_from_vault_index


def test_empty_vault_index_returns_research() -> None:
    assert infer_phase_from_vault_index({}) == "research"


def test_none_values_treated_as_empty() -> None:
    assert infer_phase_from_vault_index({"research": [], "adr": []}) == "research"


def test_single_phase_research() -> None:
    assert infer_phase_from_vault_index({"research": ["r1.md"]}) == "research"


def test_single_phase_adr() -> None:
    assert infer_phase_from_vault_index({"adr": ["adr-001.md"]}) == "adr"


def test_single_phase_exec() -> None:
    assert infer_phase_from_vault_index({"exec": ["exec-step-001.md"]}) == "exec"


def test_single_phase_audit() -> None:
    assert infer_phase_from_vault_index({"audit": ["audit-001.md"]}) == "audit"


def test_highest_wins_audit_over_exec() -> None:
    result = infer_phase_from_vault_index({"exec": ["e.md"], "audit": ["a.md"]})
    assert result == "audit"


def test_highest_wins_exec_over_plan() -> None:
    result = infer_phase_from_vault_index({"plan": ["p.md"], "exec": ["e.md"]})
    assert result == "exec"


def test_highest_wins_plan_over_adr() -> None:
    result = infer_phase_from_vault_index({"adr": ["a.md"], "plan": ["p.md"]})
    assert result == "plan"


def test_highest_wins_adr_over_reference() -> None:
    result = infer_phase_from_vault_index({"reference": ["r.md"], "adr": ["a.md"]})
    assert result == "adr"


def test_highest_wins_reference_over_research() -> None:
    result = infer_phase_from_vault_index(
        {"research": ["r.md"], "reference": ["ref.md"]}
    )
    assert result == "reference"


def test_all_phases_present_returns_audit() -> None:
    vault_index = {phase: [f"{phase}.md"] for phase in PHASE_ORDER}
    assert infer_phase_from_vault_index(vault_index) == "audit"


def test_unknown_phases_ignored() -> None:
    result = infer_phase_from_vault_index({"unknown_phase": ["x.md"]})
    assert result == "research"


def test_empty_lists_treated_as_absent() -> None:
    result = infer_phase_from_vault_index({"audit": [], "exec": [], "plan": ["p.md"]})
    assert result == "plan"


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_each_phase_alone(phase: str) -> None:
    result = infer_phase_from_vault_index({phase: [f"{phase}-artifact.md"]})
    assert result == phase
