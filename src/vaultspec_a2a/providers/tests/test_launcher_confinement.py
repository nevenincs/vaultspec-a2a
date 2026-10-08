"""Provider launchers resolve from the service, never from the agent workspace.

Drives the production classification and spawn seams against a real workspace
that plants its own ``node``, and completes a real ACP ``initialize`` handshake
with the pinned adapter to prove which binary actually ran.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ...testing import ACP_PROTOCOL_VERSION, exchange_acp_request, initialize_request
from ...workspace.environment import resolve_env_vars
from .._factory_commands import _classify_acp_command, claude_acp_entry
from .._subprocess import kill_process_tree, spawn_acp_process
from ..cli_resolution import _absolute_search_directories, resolve_service_executable

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


@pytest.mark.asyncio
async def test_workspace_planted_node_never_launches_the_adapter(
    tmp_path: Path,
    installed_acp_adapter: Path,
) -> None:
    """A workspace ``.venv/bin/node`` does not become the provider's runtime."""
    del installed_acp_adapter
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planted = _plant_workspace_node(workspace)

    env = resolve_env_vars(workspace)
    # The hijack vector is live: the agent environment really does lead with the
    # directory holding the planted launcher.
    assert env["PATH"].split(os.pathsep)[0] == str(planted.parent)

    command = _classify_acp_command("node")
    process = await spawn_acp_process(
        list(command.argv), env, str(workspace), metadata=None
    )
    try:
        # A planted launcher answers no handshake, so the reader's failure names
        # what the child wrote instead, which is where its marker would show.
        frame = await exchange_acp_request(
            process,
            initialize_request(
                _INITIALIZE_ID,
                "vaultspec",
                {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            ),
            _HANDSHAKE_TIMEOUT_SECONDS,
        )
        result = frame.get("result")
        assert isinstance(result, dict), frame
        assert result["protocolVersion"] == ACP_PROTOCOL_VERSION
    finally:
        await kill_process_tree(process)


def test_classified_acp_command_names_an_absolute_service_runtime(
    installed_acp_adapter: Path,
) -> None:
    """The Claude ACP command carries the service's own Node, by absolute path."""
    del installed_acp_adapter
    command = _classify_acp_command("node")

    assert command.argv == (
        resolve_service_executable("node"),
        str(claude_acp_entry()),
    )
    assert Path(command.argv[0]).is_absolute()
    assert Path(command.argv[0]).is_file()
    assert command.command_executable == Path(command.argv[0]).name
    assert command.command_target == str(claude_acp_entry())


def test_trusted_search_drops_working_directory_entries(tmp_path: Path) -> None:
    """Relative and empty search entries never take part in resolution."""
    search_path = os.pathsep.join(["", ".", "relative/bin", str(tmp_path)])

    assert _absolute_search_directories(search_path) == (str(tmp_path),)


def test_trusted_resolution_refuses_a_name_carrying_a_directory() -> None:
    """Resolution answers for bare names only, so a path cannot smuggle a lookup."""
    with pytest.raises(ValueError, match="bare name"):
        resolve_service_executable(os.path.join("any", "node"))
