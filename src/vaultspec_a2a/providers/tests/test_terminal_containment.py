"""Real-process proof that an ACP terminal child is OS-contained and reaped whole.

Drives ``on_terminal_create`` to spawn a genuine allowlisted terminal child (a
real Python process that itself spawns a grandchild), proves the child is seated
in its own containment before it runs, and proves ``on_terminal_kill`` reaps the
whole terminal subtree through that containment. ``service``-marked: real
subprocesses, no mock.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, cast

import pytest

from vaultspec_a2a.lifecycle.discovery import is_pid_alive
from vaultspec_a2a.utils.process import ProcessContainment

from .._acp_rpc_handlers import on_terminal_create, on_terminal_kill
from .._acp_types import _AcpModelConfig, _AcpSessionContext

# A script (run by path, so the terminal args carry no shell metacharacters the
# allowlist guard rejects) that spawns a long-lived grandchild, prints its pid,
# then sleeps.
_GRANDCHILD_SCRIPT = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(g.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def _make_config(workspace_root: str) -> _AcpModelConfig:
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace_root,
        cwd=None,
        command=["python"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


class _Ctx:
    def __init__(self) -> None:
        self.stdin_lock = asyncio.Lock()
        self.terminals: dict[str, Any] = {}
        self.interrupt_exc: list[Any] = []
        self.chunk_queue: asyncio.Queue[Any] = asyncio.Queue()


@pytest.mark.service
@pytest.mark.asyncio
async def test_terminal_child_contained_and_reaped_whole(tmp_path) -> None:
    config = _make_config(str(tmp_path))
    ctx = _Ctx()

    script = tmp_path / "spawn_grandchild.py"
    script.write_text(_GRANDCHILD_SCRIPT, encoding="utf-8")

    session_ctx = cast("_AcpSessionContext", ctx)
    resp = await on_terminal_create(
        1,
        {"command": sys.executable, "args": [str(script)]},
        session_ctx,
        config,
    )
    terminal_id = cast("dict[str, Any]", resp["result"])["terminalId"]
    process = ctx.terminals[terminal_id]

    # The terminal child is seated in its own containment before it runs.
    containment = getattr(process, "_vaultspec_containment", None)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    assert process.stdout is not None
    line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
    grandchild_pid = int(line.strip())
    try:
        assert is_pid_alive(grandchild_pid)

        # terminal/kill reaps the whole terminal subtree via the containment.
        await on_terminal_kill(2, {"terminalId": terminal_id}, session_ctx, config)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            time.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if is_pid_alive(grandchild_pid):
            from vaultspec_a2a.utils.process import kill_pid_tree_async

            await kill_pid_tree_async(grandchild_pid)
