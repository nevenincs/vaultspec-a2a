"""The recursion budget one accepted dispatch carries is decided once, here.

The operator ceiling bounds every graph invocation and the budget an accepted
preset declares can only lower it. The worker runs the number it is handed, so
this is the one place the two are weighed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain_config import domain_config
from ...team.team_config import load_team_config
from ...thread.executable_graph import freeze_graph_definition
from ..leased_dispatch import accepted_recursion_budget

if TYPE_CHECKING:
    from pathlib import Path

    from ...thread.executable_graph import FrozenGraphDefinition

_PRESET = "mock-success-single"
_LARGEST_PRESET_BUDGET = 500


def _definition(workspace: Path, *, budget: int | None = None) -> FrozenGraphDefinition:
    """The mock preset frozen as admission freezes it, re-budgeted on request."""
    team = load_team_config(_PRESET, workspace_root=workspace)
    if budget is not None:
        team = team.model_copy(
            update={"graph": team.graph.model_copy(update={"recursion_limit": budget})}
        )
    return freeze_graph_definition(team, workspace_root=workspace)


def test_a_preset_budget_below_the_ceiling_is_the_budget(tmp_path: Path) -> None:
    preset_budget = load_team_config(_PRESET).graph.recursion_limit

    assert preset_budget < domain_config.graph_recursion_limit
    assert accepted_recursion_budget(_definition(tmp_path)) == preset_budget


def test_a_preset_budget_above_the_ceiling_is_held_to_the_ceiling(
    tmp_path: Path,
) -> None:
    definition = _definition(tmp_path, budget=_LARGEST_PRESET_BUDGET)

    assert definition.recursion_limit == _LARGEST_PRESET_BUDGET
    assert accepted_recursion_budget(definition) == domain_config.graph_recursion_limit
