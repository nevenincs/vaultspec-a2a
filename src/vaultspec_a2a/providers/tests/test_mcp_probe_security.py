"""Real MCP probes cannot resolve workspace-owned package runners."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from ...testing.children import run_child

if TYPE_CHECKING:
    from pathlib import Path


def test_workspace_uvx_and_python_never_supply_the_contract_probe(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    scripts = workspace / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    scripts.mkdir(parents=True)
    marker = workspace / "hijacked"
    for name in ("uvx", "python", "python3"):
        if os.name == "nt":
            planted = scripts / f"{name}.cmd"
            planted.write_text(f'@echo hijacked > "{marker}"\r\n', encoding="utf-8")
        else:
            planted = scripts / name
            planted.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
            planted.chmod(0o755)

    # A fresh interpreter guarantees that a previous successful probe cannot
    # satisfy this test from the process cache.
    script = f"""
import asyncio, os
from pathlib import Path
from vaultspec_a2a.workspace.environment import resolve_env_vars
from vaultspec_a2a.providers._acp_mcp import resolve_harness_mcp_servers
from vaultspec_a2a.providers._mcp_contract import verify_harness_mcp_contract
env = resolve_env_vars(Path({str(workspace)!r}))
assert env['PATH'].split(os.pathsep)[0] == {str(scripts)!r}
specs = resolve_harness_mcp_servers(['vaultspec-rag'])
assert Path(specs[0]['command']).is_absolute()
asyncio.run(verify_harness_mcp_contract(specs, env=env))
assert not Path({str(marker)!r}).exists()
print('trusted MCP contract verified')
"""
    completed = run_child(
        [sys.executable, "-c", script],
        what="MCP probe with workspace-shadowed uvx and Python",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "trusted MCP contract verified" in completed.stdout
    assert not marker.exists()
