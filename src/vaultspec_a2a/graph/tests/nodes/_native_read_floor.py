"""The native read floor as a worker's provider session receives it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....providers._claude_tool_policy import workspace_scoped_tool_rule
from ....providers._native_read_tools import NATIVE_READ_TOOL_NAMES

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scoped_read_floor"]


def scoped_read_floor(workspace: Path) -> list[str]:
    """The read floor scoped to the run's workspace.

    A bare built-in name permits the tool anywhere on the host, so the floor is
    composed under the run's own workspace wherever the tool's permission grammar
    accepts a path. Read through the production seam rather than restated,
    because which tools take a path is the installed SDK's answer, not a test's.
    """
    return [
        workspace_scoped_tool_rule(name, str(workspace))
        for name in NATIVE_READ_TOOL_NAMES
    ]
