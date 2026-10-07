"""Current-schema provider authority fixture used by control behavior tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ...graph.enums import Provider
from ...providers.team_selection import freeze_team_selection
from ...testing import in_process_lane_selection

if TYPE_CHECKING:
    from pathlib import Path


def current_execution_metadata(
    workspace: Path, *, required_roles: tuple[str, ...] = ("coder",)
) -> str:
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
