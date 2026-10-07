"""The current-schema execution metadata a thread row carries for its run.

Control, worker, database and api tests that seat a thread row directly, rather
than starting a run over the gateway, still need the execution authority that row
must carry: the workspace root and a frozen provider-catalog selection. This
builds it through production's team-selection freezer over the offline
deterministic lane, so no test tier restates the record's shape.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..graph.enums import Provider
from ..providers.team_selection import freeze_team_selection
from .catalog import in_process_lane_selection

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["current_execution_metadata"]


def current_execution_metadata(
    workspace: Path, *, required_roles: tuple[str, ...] = ("coder",)
) -> str:
    """Return the serialized execution metadata of a deterministic-lane run."""
    record, selection = in_process_lane_selection(Provider.DETERMINISTIC)
    frozen = freeze_team_selection(
        selection=selection,
        overrides={},
        fallbacks=(),
        required_roles=required_roles,
        records=(record,),
    )
    return json.dumps(
        {
            "workspace_root": str(workspace.resolve()),
            "provider_catalog_selection": frozen.to_record(),
        }
    )
