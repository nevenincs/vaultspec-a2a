"""The native read floor as a worker's provider session receives it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....providers._native_read_tools import native_read_floor_rules

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scoped_read_floor"]


def scoped_read_floor(workspace: Path) -> list[str]:
    """The read floor scoped to the run's workspace.

    Read through the production seam rather than restated, because which tools
    take a path is the installed SDK's answer, not a test's. The seam's own
    contents are pinned by the provider tests.
    """
    return native_read_floor_rules(str(workspace))
