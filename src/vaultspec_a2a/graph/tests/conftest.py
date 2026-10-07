"""Fixtures for graph-layer tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ...providers import ProviderFactory
from ...providers.team_selection import FrozenLaneAssignment, LaneProvenance
from ..enums import Provider

if TYPE_CHECKING:
    from ..protocols import ProviderFactoryProtocol


@pytest.fixture
def pf() -> ProviderFactoryProtocol:
    """The real provider factory, which serves the deterministic lane in tests."""
    return ProviderFactory()


def deterministic_model_assignment(
    team_config: Any,
) -> dict[str, FrozenLaneAssignment]:
    """Build exact schema-v1 assignments for topology-only graph tests."""
    assignment = FrozenLaneAssignment(
        schema_version=1,
        provider_id=Provider.DETERMINISTIC,
        execution_mode="in-process-deterministic",
        catalog_revision="test-revision",
        entry_id="test-entry",
        model_name="deterministic",
        controls=(),
        defaulted_control_ids=(),
        provenance=LaneProvenance(selection_source="team_selection"),
    )
    return {
        "__supervisor__": assignment,
        **{ref.agent_id: assignment for ref in team_config.workers},
    }
