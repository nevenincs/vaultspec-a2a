"""Unisolated terminal RPCs cannot delegate the worker's host authority."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from .._acp_rpc_terminal_handlers import on_terminal_create
from .test_desktop_workspace_boundary import _config

if TYPE_CHECKING:
    from pathlib import Path

    from .._acp_types import AcpSessionContext


@pytest.mark.asyncio
@pytest.mark.parametrize("command_kind", ["absolute", "basename", "workspace-shadow"])
async def test_unisolated_interpreter_cannot_read_or_write_outside_workspace(
    tmp_path: Path, acp_session_context: AcpSessionContext, command_kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private = tmp_path / "private.txt"
    private.write_text("private-control", encoding="utf-8")
    stolen = workspace / "stolen.txt"
    script = workspace / "escape.py"
    script.write_text(
        "from pathlib import Path\n"
        f"private = Path({json.dumps(str(private))})\n"
        f"Path({json.dumps(str(stolen))}).write_text(private.read_text())\n"
        "private.write_text('modified')\n",
        encoding="utf-8",
    )
    command = sys.executable if command_kind == "absolute" else "python"
    if command_kind == "workspace-shadow":
        command = str(workspace / "python.exe")
        (workspace / "python.exe").write_bytes(b"workspace-controlled executable")
    response = await on_terminal_create(
        1,
        {
            "sessionId": acp_session_context.session_id,
            "command": command,
            "args": [str(script)],
        },
        acp_session_context,
        _config(workspace),
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32603,
            "message": "ACP terminal requires workspace OS isolation",
        },
    }
    assert private.read_text(encoding="utf-8") == "private-control"
    assert not stolen.exists()
    assert not acp_session_context.terminals
