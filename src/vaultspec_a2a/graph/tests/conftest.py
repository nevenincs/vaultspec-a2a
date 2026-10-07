"""Fixtures for graph-layer tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...control.run_start_policy import required_role_ids
from ...providers import ProviderFactory
from ...providers.team_selection import FrozenLaneAssignment, freeze_team_selection
from ...testing import in_process_lane_selection
from ..enums import Provider

if TYPE_CHECKING:
    from ...team.team_config import TeamConfig
    from ..protocols import ProviderFactoryProtocol


@pytest.fixture
def pf() -> ProviderFactoryProtocol:
    """The real provider factory, which serves the deterministic lane in tests."""
    return ProviderFactory()


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
