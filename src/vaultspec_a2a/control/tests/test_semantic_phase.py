"""Unit tests for the semantic authoring-phase projection (P02.S04).

Pure logic - the projection maps thread status, checkpoint next-node position,
and repair posture to the product-safe phase vocabulary the Rust backend reads.
"""

from __future__ import annotations

import pytest

from vaultspec_a2a.control.thread_state_service import project_semantic_phase
from vaultspec_a2a.thread.enums import RepairStatus, ThreadStatus


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ThreadStatus.COMPLETED.value, "completed"),
        (ThreadStatus.ARCHIVED.value, "completed"),
        (ThreadStatus.FAILED.value, "failed"),
        (ThreadStatus.CANCELLED.value, "cancelled"),
        (ThreadStatus.CANCELLING.value, "cancelled"),
    ],
)
def test_terminal_statuses_map_directly(status: str, expected: str) -> None:
    assert (
        project_semantic_phase(status=status, next_nodes=[], repair_status=None)
        == expected
    )


@pytest.mark.parametrize(
    "status", [ThreadStatus.REPAIR_NEEDED.value, ThreadStatus.RECONCILING.value]
)
def test_recovery_statuses_project_recovery_required(status: str) -> None:
    assert (
        project_semantic_phase(status=status, next_nodes=[], repair_status=None)
        == "recovery_required"
    )


def test_recovery_repair_posture_projects_recovery_required() -> None:
    assert (
        project_semantic_phase(
            status=ThreadStatus.RUNNING.value,
            next_nodes=["synthesis"],
            repair_status=RepairStatus.NEEDS_RECONCILIATION.value,
        )
        == "recovery_required"
    )


def test_transient_checkpoint_unavailable_is_not_recovery() -> None:
    """A fresh dispatch with no checkpoint yet is running, not recovery."""
    assert (
        project_semantic_phase(
            status=ThreadStatus.RUNNING.value,
            next_nodes=[],
            repair_status=RepairStatus.CHECKPOINT_UNAVAILABLE.value,
        )
        == "running"
    )


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("research_dispatch", "researching"),
        ("research_dispatch_researcher_00", "researching"),
        ("mount_research_dispatch_researcher_01", "researching"),
        ("synthesis", "synthesizing_research"),
        ("research_review", "reviewing_research"),
        ("research_gate", "awaiting_research_decision"),
        ("adr_author", "writing_adr"),
        ("adr_review", "reviewing_adr"),
        ("adr_gate", "awaiting_adr_decision"),
    ],
)
def test_research_adr_node_positions_project_phases(node: str, expected: str) -> None:
    assert (
        project_semantic_phase(
            status=ThreadStatus.RUNNING.value, next_nodes=[node], repair_status=None
        )
        == expected
    )


def test_submitted_projects_starting() -> None:
    assert (
        project_semantic_phase(
            status=ThreadStatus.SUBMITTED.value, next_nodes=[], repair_status=None
        )
        == "starting"
    )


def test_non_research_adr_running_projects_generic_running() -> None:
    """A coder run (unknown node, or none) gets an honest generic phase."""
    assert (
        project_semantic_phase(
            status=ThreadStatus.RUNNING.value,
            next_nodes=["vaultspec-coder"],
            repair_status=None,
        )
        == "running"
    )


def test_end_and_empty_nodes_are_skipped() -> None:
    assert (
        project_semantic_phase(
            status=ThreadStatus.RUNNING.value,
            next_nodes=["__end__", "", "adr_review"],
            repair_status=None,
        )
        == "reviewing_adr"
    )
