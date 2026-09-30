"""Provider launchers resolve from the service, never from the agent workspace.

Drives the production classification and spawn seams against a real workspace
that plants its own ``node``, and completes a real ACP ``initialize`` handshake
with the pinned adapter to prove which binary actually ran.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...workspace.environment import resolve_env_vars
from .._factory_commands import _CLAUDE_ACP_JS, _classify_acp_command
from .._subprocess import kill_process_tree, spawn_acp_process
from ..cli_resolution import _trusted_search_directories, resolve_trusted_executable

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_HIJACK_MARKER = "planted-launcher-executed"
_HANDSHAKE_TIMEOUT_SECONDS = 60.0
_INITIALIZE_ID = 1


def _plant_workspace_node(workspace: Path) -> Path:
    """Write an executable ``node`` into the venv the agent PATH leads with."""
    bin_dir = workspace / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    bin_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        planted = bin_dir / "node.cmd"
        planted.write_text(f"@echo {_HIJACK_MARKER}\r\n", encoding="utf-8")
        return planted
    planted = bin_dir / "node"
    planted.write_text(f"#!/bin/sh\necho {_HIJACK_MARKER}\n", encoding="utf-8")
    planted.chmod(0o755)
    return planted


async def _read_initialize_result(stdout: asyncio.StreamReader) -> JsonObject:
    """Return the ``initialize`` response, reporting what the child said instead."""
    seen: list[str] = []
    for _ in range(60):
        raw = await asyncio.wait_for(
            stdout.readline(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        if not raw:
            break
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        seen.append(text)
        assert _HIJACK_MARKER not in text, (
            f"the workspace-planted launcher executed instead of the adapter: {seen}"
        )
        try:
            frame = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(frame, dict) and frame.get("id") == _INITIALIZE_ID:
            result = frame.get("result")
            assert isinstance(result, dict), frame
            return result
    raise AssertionError(f"no initialize response; child wrote {seen}")


@pytest.mark.asyncio
async def test_workspace_planted_node_never_launches_the_adapter(
    tmp_path: Path,
) -> None:
    """A workspace ``.venv/bin/node`` does not become the provider's runtime."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planted = _plant_workspace_node(workspace)

    env = resolve_env_vars(workspace)
    # The hijack vector is live: the agent environment really does lead with the
    # directory holding the planted launcher.
    assert env["PATH"].split(os.pathsep)[0] == str(planted.parent)

    command, _metadata = _classify_acp_command("node")
    process = await spawn_acp_process(command, env, str(workspace), metadata=None)
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        request = {
            "jsonrpc": "2.0",
            "id": _INITIALIZE_ID,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "vaultspec", "version": "1.0.0"},
            },
        }
        process.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
        await process.stdin.drain()
        result = await _read_initialize_result(process.stdout)
        assert result["protocolVersion"] == 1
    finally:
        await kill_process_tree(process)


def test_classified_acp_command_names_an_absolute_service_runtime() -> None:
    """The Claude ACP command carries the service's own Node, by absolute path."""
    command, metadata = _classify_acp_command("node")

    assert command == [resolve_trusted_executable("node"), str(_CLAUDE_ACP_JS)]
    assert Path(command[0]).is_absolute()
    assert Path(command[0]).is_file()
    assert metadata["command_executable"] == Path(command[0]).name
    assert metadata["command_target"] == str(_CLAUDE_ACP_JS)


def test_trusted_search_drops_working_directory_entries() -> None:
    """Relative and empty search entries never take part in resolution."""
    search_path = os.pathsep.join(["", ".", "relative/bin", os.sep + "usr/bin"])

    assert _trusted_search_directories(search_path) == (os.sep + "usr/bin",)


def test_trusted_resolution_refuses_a_name_carrying_a_directory() -> None:
    """Resolution answers for bare names only, so a path cannot smuggle a lookup."""
    with pytest.raises(ValueError, match="bare name"):
        resolve_trusted_executable(os.path.join("any", "node"))
