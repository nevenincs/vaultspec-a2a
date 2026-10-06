"""Real retained processes for output, ownership and cleanup tests.

These tests start below terminal admission. Workspace isolation admission is
exercised separately through the actual terminal/create handler.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from uuid import uuid4

from .._acp_terminal_output import MAX_TERMINAL_OUTPUT_BYTES, AcpTerminalOutput
from .._subprocess import spawn_acp_process

if TYPE_CHECKING:
    from pathlib import Path

    from .._acp_types import AcpSessionContext


async def retain_terminal_process(
    ctx: AcpSessionContext,
    root: Path,
    args: list[str],
    limit: int = MAX_TERMINAL_OUTPUT_BYTES,
) -> str:
    process = await spawn_acp_process(
        [sys.executable, *args], {}, str(root), use_exec=True
    )
    terminal_id = uuid4().hex
    ctx.terminals[terminal_id] = process
    ctx.terminal_outputs[terminal_id] = AcpTerminalOutput.capture(process, limit)
    return terminal_id
