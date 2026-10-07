"""Desktop native commands refuse before inheriting private-state authority."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...control.provider_execution import (
    NativeExecutionRefusedError,
    native_execution_refusal_reason,
)
from ...control.state_layout import state_layout
from ...graph.enums import Provider
from ...testing import armed_desktop_app_home, settings_override
from .._acp_rpc_terminal_handlers import on_terminal_create
from .._acp_types import AcpSessionContext
from .._provider_execution import provider_execution_command
from .._subprocess import (
    kill_process_tree,
    spawn_acp_process,
)
from ..binary_version import BinaryVersionProbeError, probe_binary_version
from ..provider_readiness import probe_provider_readiness
from .test_desktop_workspace_boundary import _config

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject


def _command(project: Path, private: Path, marker: Path) -> list[str]:
    script = project / "native-read.py"
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(Path({str(private)!r}).read_text())\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_exec", (False, True))
@pytest.mark.parametrize("identity_configured", (False, True))
async def test_desktop_native_read_is_refused_before_child_execution(
    tmp_path: Path, use_exec: bool, identity_configured: bool
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    private = home / "lifecycle-secret.txt"
    private.write_text("synthetic-private-state", encoding="utf-8")
    marker = project / "child-started.txt"
    command = _command(project, private, marker)
    with (
        armed_desktop_app_home(home),
        settings_override(
            provider_identity_launcher=sys.executable if identity_configured else None,
            provider_agent_uid=1002 if identity_configured else None,
            provider_agent_gid=1002 if identity_configured else None,
        ),
    ):
        with pytest.raises(NativeExecutionRefusedError, match="OS isolation backend"):
            await spawn_acp_process(
                command, dict(os.environ), str(project), use_exec=use_exec
            )
        for supervise in (False, True):
            with pytest.raises(
                NativeExecutionRefusedError, match="OS isolation backend"
            ):
                provider_execution_command(command, supervise=supervise)
        with pytest.raises(BinaryVersionProbeError, match="OS isolation backend"):
            probe_binary_version(sys.executable)
        for provider in (Provider.CLAUDE, Provider.CODEX, Provider.ZAI, Provider.KIMI):
            verdict = probe_provider_readiness(provider)
            assert not verdict.ready
            assert verdict.reason == native_execution_refusal_reason()
        # A lane this build holds in-process launches nothing native, so the
        # refusal does not reach it; plugin lanes are not held under this profile.
        assert probe_provider_readiness(Provider.MOCK).ready
    assert not marker.exists()
    assert private.read_text(encoding="utf-8") == "synthetic-private-state"


@pytest.mark.asyncio
async def test_desktop_terminal_refuses_before_creating_child(tmp_path: Path) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    private = home / "lifecycle-secret.txt"
    private.write_text("synthetic-private-state", encoding="utf-8")
    marker = project / "terminal-started.txt"
    command = _command(project, private, marker)
    # An existing real stream owner supplies the session context; it is created
    # before arming, and no native agent/tool child is permitted after arming.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "pass",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    ctx = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[1],
        interrupt_exc=[],
        session_id="terminal-refusal",
    )
    try:
        with settings_override(desktop_app_home=home, provider_identity_launcher=None):
            params: JsonObject = {
                "sessionId": ctx.session_id,
                "command": command[0],
                "args": list(command[1:]),
            }
            response = await on_terminal_create(1, params, ctx, _config(project))
            assert response["error"] == {
                "code": -32603,
                "message": native_execution_refusal_reason(),
            }
        assert ctx.terminals == {}
        assert not marker.exists()
    finally:
        await kill_process_tree(process)


@pytest.mark.asyncio
@pytest.mark.parametrize("use_exec", (False, True))
async def test_unarmed_native_project_execution_remains_available(
    tmp_path: Path, use_exec: bool
) -> None:
    project_file = tmp_path / "project.txt"
    project_file.write_text("legitimate-project-control", encoding="utf-8")
    marker = tmp_path / "native-output.txt"
    command = _command(tmp_path, project_file, marker)
    with settings_override(
        desktop_app_home=None,
        provider_identity_launcher=None,
        provider_agent_uid=None,
        provider_agent_gid=None,
    ):
        process = await spawn_acp_process(
            command, dict(os.environ), str(tmp_path), use_exec=use_exec
        )
        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == 0, stderr
            assert marker.read_text(encoding="utf-8") == "legitimate-project-control"
        finally:
            await kill_process_tree(process)
