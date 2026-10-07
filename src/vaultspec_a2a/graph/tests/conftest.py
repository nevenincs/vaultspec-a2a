"""Fixtures for graph-layer tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ...control.run_start_policy import required_role_ids
from ...providers.team_selection import FrozenLaneAssignment, freeze_team_selection
from ...testing import in_process_lane_selection
from ..enums import Provider
from ..protocols import ProviderFactoryProtocol

if TYPE_CHECKING:
    from ...team.team_config import TeamConfig

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
    team_config: TeamConfig,
) -> dict[str, FrozenLaneAssignment]:
    """Compile *team_config*'s per-role assignment on the offline deterministic lane.

    Frozen by production's team-selection freezer over the lane's served record,
    for the roles a run of this team must cover, so the assignment a graph test
    compiles against is the one a real run would hand the worker.
    """
    record, selection = in_process_lane_selection(Provider.DETERMINISTIC)
    return freeze_team_selection(
        selection=selection,
        overrides={},
        fallbacks=(),
        required_roles=tuple(required_role_ids(team_config)),
        records=(record,),
    ).compiler_map()
