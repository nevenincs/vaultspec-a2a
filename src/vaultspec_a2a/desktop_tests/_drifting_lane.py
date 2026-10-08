"""A fixture lane whose served catalog moves when a marker file appears.

Run start revalidates a request's provider selection against the catalog served
for the run's workspace. Proving that a staged commit no longer repeats that
validation needs a catalog that really MOVES between the prepare and the commit,
and no static lane can provide one: the deterministic fixture lane's entries are
fixed, so every rediscovery yields the same revision and a repeated validation
is indistinguishable from none at all.

This plugin therefore registers the deterministic lane's identity and model and
adds one extra selector while a marker file exists under the configured
workspace root. A lane's catalog revision is a digest of its model list, so the
marker moves the revision, and the gateway's own provider-catalog verb serves
the new one - which is what a scenario observes before it commits. The marker is
created by the test, so the drift happens exactly when the scenario says it
does rather than on a timer.

The lane keeps the deterministic lane's wire identity and model, so a run frozen
against either replays under the same identity and executes the same scripted
content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ..testing.lanes import DETERMINISTIC_LANE

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.language_models import BaseChatModel

    from ..graph.enums import Provider
    from ..providers import LaneRegistry
    from ..team.team_config import AgentConfig

#: Only the marker name is imported by a caller. ``register_lanes`` below is the
#: lane-plugin entry point, which the registry resolves by name on the imported
#: module rather than importing, so publishing it would declare an export
#: nothing consumes.
__all__ = ["MARKER_NAME"]

#: The file whose presence under the workspace root adds the extra selector.
MARKER_NAME: Final = ".catalog-drift"

#: The selector this lane advertises only while the marker exists.
DRIFTED_MODEL: Final = "deterministic-drifted"


def drift_marker() -> Path | None:
    """Return the marker path this process watches, or ``None`` when unrooted.

    Read per access rather than captured once: the whole point is that the
    answer changes while the process runs.
    """
    from ..control.config import settings

    root = settings.workspace_root
    return None if root is None else root / MARKER_NAME


@dataclass(frozen=True, slots=True)
class _DriftingLane:
    """The deterministic lane, with one selector that comes and goes."""

    provider: Provider = DETERMINISTIC_LANE.provider
    execution_mode: str = DETERMINISTIC_LANE.execution_mode
    display_name: str = DETERMINISTIC_LANE.display_name
    description: str = DETERMINISTIC_LANE.description

    @property
    def model_values(self) -> tuple[str, ...]:
        """The lane's selectors, one more of them once the marker exists."""
        marker = drift_marker()
        if marker is not None and marker.exists():
            return (*DETERMINISTIC_LANE.model_values, DRIFTED_MODEL)
        return DETERMINISTIC_LANE.model_values

    def create_model(self, agent_config: AgentConfig | None) -> BaseChatModel:
        """Build the deterministic lane's model, whichever selector was frozen."""
        return DETERMINISTIC_LANE.create_model(agent_config)


def register_lanes(registry: LaneRegistry) -> None:
    """Register this lane; the lane-plugin entry point."""
    registry.register(_DriftingLane())
