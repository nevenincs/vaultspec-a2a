"""Real native launch/terminal seams preserve explicit filesystem authority."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...desktop.tests.test_native_isolation import _authority, _install_runtime
from ...testing import settings_override
from ...utils.process import ProcessContainmentError
from .._acp_mcp import resolve_harness_mcp_servers
from .._acp_rpc_terminal_handlers import on_terminal_create, on_terminal_release
from .._acp_types import AcpSessionContext
from .._harness_mcp_registry import declared_harness_tools
from .._mcp_contract import verify_declared_tool_contract
from .._provider_execution import provider_execution_launch
from .._subprocess import kill_process_tree, process_native_authority, spawn_acp_process
from ..binary_version import BinaryVersionProbeError, probe_binary_version
from ._native_mcp_capsule import install_mcp_runtime
from .test_desktop_workspace_boundary import _config

if TYPE_CHECKING:
    from pathlib import Path


def test_explicit_authority_cannot_bypass_armed_refusal(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    with settings_override(desktop_app_home=authority.app_home.path):
        with pytest.raises(ProcessContainmentError, match="OS isolation backend"):
            provider_execution_launch(
                [sys.executable],
                environment={},
                cwd=str(authority.workspace.path),
                native_authority=authority,
            )
        with pytest.raises(BinaryVersionProbeError, match="OS isolation backend"):
            probe_binary_version(sys.executable, native_authority=authority)


@pytest.mark.asyncio
async def test_shared_spawn_and_terminals_keep_session_authority(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    if sys.platform != "linux":
        with pytest.raises(ProcessContainmentError, match="requires Linux"):
            await spawn_acp_process(
                [sys.executable],
                {},
                str(authority.workspace.path),
                native_authority=authority,
            )
        return
    node = _install_runtime(authority)
    private = authority.app_home.path / "synthetic-private"
    private.write_text("private-control", encoding="utf-8")
    hook = authority.workspace.path / "sitecustomize.py"
    hook.write_text(
        "raise RuntimeError('workspace hook must not run')\n", encoding="utf-8"
    )
    terminal_script = authority.workspace.path / "terminal.js"
    terminal_script.write_text(
        "const fs = require('fs'); let result;\n"
        + f"try {{ fs.readFileSync({json.dumps(str(private))});\n"
        + "result='permitted'; }\n"
        + "catch(e) { result=e.code; }\n"
        + "fs.writeFileSync('terminal-write', process.env.ROLE_OPTION);\n"
        + "console.log(JSON.stringify({read:result,home:process.env.HOME}));\n",
        encoding="utf-8",
    )
    owner = await spawn_acp_process(
        [str(node), "-e", "setInterval(() => {}, 1000)"],
        {**os.environ, "PYTHONPATH": str(authority.workspace.path)},
        str(authority.workspace.path),
        native_authority=authority,
    )
    assert owner.stdin is not None and owner.stdout is not None
    ctx = AcpSessionContext(
        process=owner,
        stdin=owner.stdin,
        stdout=owner.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[1],
        interrupt_exc=[],
        session_id="isolated-role-control",
    )
    try:
        assert process_native_authority(owner) == authority
        response = await on_terminal_create(
            1,
            {
                "sessionId": ctx.session_id,
                "command": str(node),
                "args": [str(terminal_script)],
                "env": {"ROLE_OPTION": "normal-option", "HOME": str(private.parent)},
            },
            ctx,
            _config(authority.workspace.path),
        )
        result = response.get("result")
        assert isinstance(result, dict), response
        terminal_id = result["terminalId"]
        assert isinstance(terminal_id, str)
        child = ctx.terminals[terminal_id]
        assert process_native_authority(child) == authority
        await asyncio.wait_for(child.wait(), timeout=15)
        output = ctx.terminal_outputs[terminal_id]
        await output.settle()
        assert child.returncode == 0, output.output
        observed = json.loads(output.output)
        assert observed == {"read": "ENOENT", "home": str(authority.home.path)}
        assert (
            authority.workspace.path / "terminal-write"
        ).read_text() == "normal-option"
        await on_terminal_release(
            2,
            {"sessionId": ctx.session_id, "terminalId": terminal_id},
            ctx,
            _config(authority.workspace.path),
        )
    finally:
        for output in ctx.terminal_outputs.values():
            await kill_process_tree(output.process)
            await output.close()
        await kill_process_tree(owner)


def test_isolated_version_cache_cannot_reuse_changed_authority(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    if sys.platform != "linux":
        with pytest.raises(BinaryVersionProbeError, match="authority is unavailable"):
            probe_binary_version(sys.executable, native_authority=authority)
        return
    _install_runtime(authority)
    executable = authority.capsule.path / "isolation" / "bin" / "bubblewrap"
    baseline = probe_binary_version(executable)
    assert probe_binary_version(executable, native_authority=authority) == baseline
    assert probe_binary_version(executable, native_authority=authority) == baseline
    original = authority.workspace.path.with_name("original")
    authority.workspace.path.rename(original)
    authority.workspace.path.mkdir()
    with pytest.raises(BinaryVersionProbeError, match="authority is unavailable"):
        probe_binary_version(executable, native_authority=authority)


@pytest.mark.asyncio
async def test_mcp_cached_surface_cannot_bypass_profile_refusal(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    spec = resolve_harness_mcp_servers(["vaultspec-rag"])[0]
    command = spec["command"]
    raw_args = spec["args"]
    assert isinstance(command, str) and isinstance(raw_args, list)
    args = [value for value in raw_args if isinstance(value, str)]
    assert len(args) == len(raw_args)
    tools = declared_harness_tools("vaultspec-rag")
    await verify_declared_tool_contract(
        name="vaultspec-rag",
        command=command,
        args=args,
        declared=tools,
    )
    with settings_override(desktop_app_home=authority.app_home.path):
        for context in (None, authority):
            with pytest.raises(ProcessContainmentError, match="OS isolation backend"):
                await verify_declared_tool_contract(
                    name="vaultspec-rag",
                    command=command,
                    args=args,
                    declared=tools,
                    native_authority=context,
                )


@pytest.mark.asyncio
async def test_genuine_mcp_handshake_uses_isolated_runtime_context(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    if sys.platform != "linux":
        with pytest.raises(ProcessContainmentError, match="requires Linux"):
            await verify_declared_tool_contract(
                name="unsupported-native-control",
                command=sys.executable,
                args=[],
                declared=[],
                native_authority=authority,
            )
        return
    executable = install_mcp_runtime(authority)
    await verify_declared_tool_contract(
        name="capsule-vaultspec-rag",
        command=str(executable),
        args=["-c", "from vaultspec_rag.server import main; main()", "--read-only"],
        declared=declared_harness_tools("vaultspec-rag"),
        env={},
        native_authority=authority,
        timeout=30,
    )
    authority.workspace.path.rename(authority.workspace.path.with_name("original"))
    authority.workspace.path.mkdir()
    with pytest.raises(OSError, match="changed"):
        await verify_declared_tool_contract(
            name="capsule-vaultspec-rag",
            command=str(executable),
            args=["-c", "from vaultspec_rag.server import main; main()", "--read-only"],
            declared=declared_harness_tools("vaultspec-rag"),
            env={},
            native_authority=authority,
            timeout=30,
        )
