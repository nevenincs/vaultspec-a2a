"""Fixtures for graph-layer tests."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ...providers.team_selection import FrozenLaneAssignment, LaneProvenance
from ..enums import Provider
from ..protocols import ProviderFactoryProtocol

# ---------------------------------------------------------------------------
# Layer 1 test stub — avoids importing the Layer 2 ProviderFactory
# ---------------------------------------------------------------------------


class _StubProviderFactory:
    """Returns a ``FakeChatModel`` for any provider."""

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        _kwargs: dict[str, Any] = {"responses": ["stub response"]}
        return FakeChatModel(**_kwargs)


@pytest.fixture
def pf() -> ProviderFactoryProtocol:
    """Stub provider factory for graph compilation tests (Layer 1 only)."""
    factory = _StubProviderFactory()
    assert isinstance(factory, ProviderFactoryProtocol)
    return factory


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
