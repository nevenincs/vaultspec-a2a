"""Real-process proofs for the ACP terminal RPC surface.

The ``service``-marked test drives ``on_terminal_create`` to spawn a genuine
allowlisted terminal child (a real Python process that itself spawns a
grandchild), proves the child is seated in its own containment before it runs,
and proves ``on_terminal_kill`` reaps the whole terminal subtree through that
containment.

The remaining tests pin the terminal-id resolution contract shared by
``terminal/kill``, ``terminal/output`` and ``terminal/wait_for_exit``: one wire
refusal for an unknown id, and ``terminal/release``'s deliberate exemption from
it. They run against real subprocesses and a real ``AcpSessionContext`` built
from that subprocess's own streams - no Docker, so they stay in the default gate
where a regression in the shared refusal is actually visible.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ...lifecycle.discovery import is_pid_alive
from ...utils.process import ProcessContainment
from .._acp_rpc_handlers import (
    on_terminal_create,
    on_terminal_kill,
    on_terminal_output,
    on_terminal_release,
    on_terminal_wait_for_exit,
)
from .._acp_types import AcpModelConfig, AcpSessionContext
from .._subprocess import process_containment
from ..acp_exceptions import AcpErrorCode

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject

# A script (run by path, so the terminal args carry no shell metacharacters the
# allowlist guard rejects) that spawns a long-lived grandchild, prints its pid,
# then sleeps.
_GRANDCHILD_SCRIPT = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(g.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def _make_config(workspace_root: str) -> AcpModelConfig:
    return AcpModelConfig(
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


@pytest.mark.service
@pytest.mark.asyncio
async def test_terminal_child_contained_and_reaped_whole(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    config = _make_config(str(tmp_path))

    script = tmp_path / "spawn_grandchild.py"
    script.write_text(_GRANDCHILD_SCRIPT, encoding="utf-8")

    resp = await on_terminal_create(
        1,
        {"command": sys.executable, "args": [str(script)]},
        acp_session_context,
        config,
    )
    response_result = resp.get("result")
    assert isinstance(response_result, dict)
    terminal_id = response_result.get("terminalId")
    assert isinstance(terminal_id, str)
    process = acp_session_context.terminals[terminal_id]

    # The terminal child is seated in its own containment before it runs.
    containment = process_containment(process)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    assert process.stdout is not None
    line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
    grandchild_pid = int(line.strip())
    try:
        assert is_pid_alive(grandchild_pid)

        # terminal/kill reaps the whole terminal subtree via the containment.
        await on_terminal_kill(
            2, {"terminalId": terminal_id}, acp_session_context, config
        )

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            await asyncio.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if is_pid_alive(grandchild_pid):
            from ...utils.process import kill_pid_tree_async

            await kill_pid_tree_async(grandchild_pid)


@pytest.mark.asyncio
async def test_unknown_terminal_refusal_is_one_contract_across_handlers(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """All three id-addressing handlers owe an unknown terminal one answer.

    The code, the message wording and the envelope are wire contract, so the
    responses must differ only in the JSON-RPC id being answered. Comparing them
    to each other - not each to a hand-copied literal - is what makes a future
    correction that lands in only one handler fail here.
    """
    config = _make_config(str(tmp_path))
    assert acp_session_context.terminals == {}
    params: JsonObject = {"terminalId": "ghost-7f3a"}

    kill = await on_terminal_kill(11, params, acp_session_context, config)
    output = await on_terminal_output(12, params, acp_session_context, config)
    waited = await on_terminal_wait_for_exit(13, params, acp_session_context, config)

    assert kill == {
        "jsonrpc": "2.0",
        "id": 11,
        "error": {
            "code": AcpErrorCode.INVALID_PARAMS,
            "message": "Unknown terminal: ghost-7f3a",
        },
    }
    # The wire value is -32602 whatever the enum is named.
    error = kill.get("error")
    assert isinstance(error, dict)
    assert error["code"] == -32602
    assert output == {**kill, "id": 12}
    assert waited == {**kill, "id": 13}


@pytest.mark.asyncio
async def test_missing_terminal_id_param_is_refused_not_raised(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """A request carrying no ``terminalId`` at all is refused on the same path."""
    config = _make_config(str(tmp_path))
    response = await on_terminal_output(21, {}, acp_session_context, config)
    assert response == {
        "jsonrpc": "2.0",
        "id": 21,
        "error": {
            "code": AcpErrorCode.INVALID_PARAMS,
            "message": "Unknown terminal: ",
        },
    }


@pytest.mark.asyncio
async def test_release_of_an_unknown_terminal_stays_idempotent(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """``terminal/release`` is exempt: releasing what is already gone succeeds.

    Guards the resolver's blast radius - folding release into the shared refusal
    would turn a benign double-release into a protocol error.
    """
    config = _make_config(str(tmp_path))
    response = await on_terminal_release(
        31, {"terminalId": "ghost"}, acp_session_context, config
    )
    assert response == {"jsonrpc": "2.0", "id": 31, "result": {}}


@pytest.mark.asyncio
async def test_known_terminal_still_resolves_to_its_live_process(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """The hit path is unchanged: a real created terminal is still addressable.

    Spawns a genuine allowlisted terminal child that writes a known marker and
    exits, then drives ``terminal/output`` and ``terminal/wait_for_exit`` against
    its real id - proving the resolver returns the live process rather than a
    refusal, and that the handlers' own result shapes survived the extraction.
    """
    config = _make_config(str(tmp_path))
    script = tmp_path / "emit.py"
    script.write_text("import sys\nsys.stdout.write('resolved-marker')\n", "utf-8")
    created = await on_terminal_create(
        41,
        {"command": sys.executable, "args": [str(script)]},
        acp_session_context,
        config,
    )
    created_result = created.get("result")
    assert isinstance(created_result, dict)
    terminal_id = created_result.get("terminalId")
    assert isinstance(terminal_id, str)
    assert terminal_id in acp_session_context.terminals

    exited = await on_terminal_wait_for_exit(
        42, {"terminalId": terminal_id}, acp_session_context, config
    )
    exit_result = exited.get("result")
    assert isinstance(exit_result, dict)
    assert exit_result["exitCode"] == 0

    output = await on_terminal_output(
        43, {"terminalId": terminal_id}, acp_session_context, config
    )
    output_result = output.get("result")
    assert isinstance(output_result, dict)
    terminal_output = output_result.get("output")
    assert isinstance(terminal_output, str)
    assert "resolved-marker" in terminal_output
    assert output_result["exitStatus"] == 0

    killed = await on_terminal_kill(
        44, {"terminalId": terminal_id}, acp_session_context, config
    )
    assert killed == {"jsonrpc": "2.0", "id": 44, "result": {}}
    # kill retires the id, so the next address of it takes the refusal path.
    assert terminal_id not in acp_session_context.terminals
    again = await on_terminal_kill(
        45, {"terminalId": terminal_id}, acp_session_context, config
    )
    error = again.get("error")
    assert isinstance(error, dict)
    assert error["code"] == -32602
