"""Real MCP probes cannot resolve workspace-owned package runners."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...testing import combined_output, run_child

if TYPE_CHECKING:
    from pathlib import Path


_CONTROL_ENV_NAMES = (
    "VAULTSPEC_A2A_GATEWAY_TOKEN",
    "VAULTSPEC_A2A_INTERNAL_TOKEN",
    "vaultspec_a2a_lifecycle_token",
    "DATABASE_URL",
    "CHECKPOINT_DATABASE_URL",
    "SQLALCHEMY_DATABASE_URI",
    "PGPASSWORD",
    "POSTGRES_PASSWORD",
    "SERVICE_TOKEN",
    "gateway_token",
    "INTERNAL_TOKEN",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ZAI_AUTH_TOKEN",
    "ZAI_API_KEY",
    "ZAI_BASE_URL",
    "ZAI_ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


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
    assert completed.returncode == 0, combined_output(completed)
    assert "trusted MCP contract verified" in completed.stdout
    assert not marker.exists()


@pytest.mark.parametrize("explicit_environment", [False, True])
def test_real_mcp_probe_receives_no_infrastructure_credentials(
    tmp_path: Path, explicit_environment: bool
) -> None:
    marker = tmp_path / "probe-environment.json"
    script = f"""
import asyncio, json, os, sys
from pathlib import Path
from vaultspec_a2a.providers._acp_mcp import resolve_harness_mcp_servers
from vaultspec_a2a.providers._harness_mcp_registry import declared_harness_tools
from vaultspec_a2a.providers._mcp_contract import verify_declared_tool_contract
from vaultspec_a2a.control.config import settings
# Load the valid parent profile before introducing the synthetic child inputs.
assert isinstance(settings.desktop_profile_armed, bool)
names = {_CONTROL_ENV_NAMES!r}
for name in names:
    os.environ[name] = 'synthetic-control-plane-' + name.upper()
os.environ['MCP_PROBE_OPTION'] = 'declared-option'
spec = resolve_harness_mcp_servers(['vaultspec-rag'])[0]
guard = '''
import json, os, subprocess, sys
from pathlib import Path
names = {_CONTROL_ENV_NAMES!r}
observed = {{name: name in os.environ for name in names}}
observed['option'] = os.environ.get('MCP_PROBE_OPTION')
Path({marker.as_posix()!r}).write_text(json.dumps(observed), encoding='utf8')
sys.exit(subprocess.call(sys.argv[1:]))
'''
asyncio.run(verify_declared_tool_contract(
    name='environment-guarded-rag', command=sys.executable,
    args=['-c', guard, spec['command'], *spec['args']],
    declared=declared_harness_tools('vaultspec-rag'),
    env=dict(os.environ) if {explicit_environment!r} else None,
))
observed = json.loads(Path({str(marker)!r}).read_text(encoding='utf8'))
assert observed.pop('option') == 'declared-option', observed
assert not any(observed.values()), observed
print('real MCP environment confined')
"""
    completed = run_child(
        [sys.executable, "-c", script],
        what="MCP infrastructure environment confinement",
    )
    assert completed.returncode == 0, combined_output(completed)
    assert "real MCP environment confined" in completed.stdout
