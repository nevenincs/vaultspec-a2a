"""Real-process proofs for the ACP terminal RPC surface.

The ``service``-marked test retains a genuine
terminal child (a real Python process that itself spawns a
grandchild), proves the child is seated in its own containment before it runs,
and proves ``on_terminal_kill`` reaps the whole terminal subtree through that
containment. Admission is tested separately through the isolated launch seam.

The remaining tests pin the terminal-id resolution contract shared by
``terminal/kill``, ``terminal/output`` and ``terminal/wait_for_exit``: one wire
refusal for an unknown id, and ``terminal/release``'s deliberate exemption from
it. They run against real subprocesses and a real ``AcpSessionContext`` built
from that subprocess's own streams - no Docker, so they stay in the default gate
where a regression in the shared refusal is actually visible.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from ...utils._process_tree import pid_is_live, wait_pid_gone_async
from ...utils.process import ProcessContainment
from .._acp_request import jsonrpc_error, jsonrpc_result
from .._acp_rpc_handlers import (
    on_terminal_kill,
    on_terminal_output,
    on_terminal_release,
    on_terminal_wait_for_exit,
)
from .._acp_types import AcpModelConfig, AcpSessionContext
from .._subprocess import process_containment
from ..acp_exceptions import AcpErrorCode
from ._terminal_process import retain_terminal_process

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
        command=["python"],
        env_vars={},
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

    terminal_id = await retain_terminal_process(
        acp_session_context, tmp_path, [str(script)]
    )
    process = acp_session_context.terminals[terminal_id]

    # The terminal child is seated in its own containment before it runs.
    containment = process_containment(process)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    async with asyncio.timeout(10):
        while not acp_session_context.terminal_outputs[terminal_id].output.strip():
            await asyncio.sleep(0.01)
    grandchild_pid = int(
        acp_session_context.terminal_outputs[terminal_id].output.strip()
    )
    try:
        assert pid_is_live(grandchild_pid)

        # terminal/kill reaps the whole terminal subtree via the containment.
        await on_terminal_kill(
            2,
            {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
            acp_session_context,
            config,
        )

        assert await wait_pid_gone_async(grandchild_pid, timeout=10.0)
    finally:
        if pid_is_live(grandchild_pid):
            from ...utils._process_tree import kill_pid_tree_async

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
    params: JsonObject = {
        "terminalId": "ghost-7f3a",
        "sessionId": acp_session_context.session_id,
    }

    kill = await on_terminal_kill(11, params, acp_session_context, config)
    output = await on_terminal_output(12, params, acp_session_context, config)
    waited = await on_terminal_wait_for_exit(13, params, acp_session_context, config)

    assert kill == jsonrpc_error(
        11, AcpErrorCode.INVALID_PARAMS, "Unknown terminal: ghost-7f3a"
    )
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
    response = await on_terminal_output(
        21, {"sessionId": acp_session_context.session_id}, acp_session_context, config
    )
    assert response["id"] == 21 and "result" not in response
    error = response.get("error")
    assert isinstance(error, dict)
    assert error["code"] == AcpErrorCode.INVALID_PARAMS
    assert "terminalId" in str(error["message"])


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
        31,
        {"sessionId": acp_session_context.session_id, "terminalId": "ghost"},
        acp_session_context,
        config,
    )
    assert response == jsonrpc_result(31, {})


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
    terminal_id = await retain_terminal_process(
        acp_session_context, tmp_path, [str(script)]
    )
    assert terminal_id in acp_session_context.terminals

    exited = await on_terminal_wait_for_exit(
        42,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert exited == jsonrpc_result(42, {"exitCode": 0, "signal": None})

    output = await on_terminal_output(
        43,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    # The whole v1 result, not a field probe: an extra or renamed key is exactly
    # the kind of drift a subset assertion would wave through.
    assert output == jsonrpc_result(
        43,
        {
            "output": "resolved-marker",
            "truncated": False,
            "exitStatus": {"exitCode": 0, "signal": None},
        },
    )

    killed = await on_terminal_kill(
        44,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert killed == jsonrpc_result(44, {})
    # kill stops the command but does NOT release the terminal, so the id stays
    # addressable and a second kill is still answered rather than refused.
    assert terminal_id in acp_session_context.terminals
    again = await on_terminal_kill(
        45,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert again == jsonrpc_result(45, {})

    # Only release ends addressability.
    released = await on_terminal_release(
        46,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert released == jsonrpc_result(46, {})
    assert terminal_id not in acp_session_context.terminals


async def _create_terminal(
    ctx: AcpSessionContext, config: AcpModelConfig, script: Path, body: str
) -> str:
    """Spawn a real allowlisted terminal child running ``body`` and return its id."""
    script.write_text(body, encoding="utf-8")
    return await retain_terminal_process(ctx, script.parent, [str(script)])


@pytest.mark.asyncio
async def test_exit_status_is_absent_while_the_command_is_still_running(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """``exitStatus`` is optional and must be OMITTED before the command exits.

    Reporting a status early would tell the agent a command finished while it is
    still running, so the absence of the key - not merely a null in it - is the
    contract being pinned.
    """
    config = _make_config(str(tmp_path))
    terminal_id = await _create_terminal(
        acp_session_context,
        config,
        tmp_path / "sleeper.py",
        "import time\ntime.sleep(120)\n",
    )
    try:
        output = await on_terminal_output(
            51,
            {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
            acp_session_context,
            config,
        )
        assert output == jsonrpc_result(51, {"output": "", "truncated": False})
        result = output["result"]
        assert isinstance(result, dict)
        assert "exitStatus" not in result
    finally:
        await on_terminal_release(
            52,
            {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
            acp_session_context,
            config,
        )


@pytest.mark.asyncio
async def test_a_nonzero_exit_code_is_reported_exactly_not_collapsed(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """A failing command reports its own code, with a null signal beside it.

    Pinning a NON-zero code catches a status builder that hardcodes success or
    coerces the code to a boolean-ish result.
    """
    config = _make_config(str(tmp_path))
    terminal_id = await _create_terminal(
        acp_session_context,
        config,
        tmp_path / "failer.py",
        "import sys\nsys.exit(7)\n",
    )
    exited = await on_terminal_wait_for_exit(
        61,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert exited == jsonrpc_result(61, {"exitCode": 7, "signal": None})
    output = await on_terminal_output(
        62,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    output_result = output.get("result")
    assert isinstance(output_result, dict)
    assert output_result["exitStatus"] == {"exitCode": 7, "signal": None}
    await on_terminal_release(
        63,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )


@pytest.mark.asyncio
async def test_a_killed_terminal_still_answers_output_and_exit_until_released(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    """Kill ends the command; the terminal stays fully usable until release.

    This is the lifetime the previous implementation could not express: it
    retired the id inside kill, so the output the agent killed the command to
    inspect became unreachable in the same call. Every id-addressing handler is
    driven AFTER the kill to prove addressability survives it, and the output
    written before the kill must still come back.
    """
    config = _make_config(str(tmp_path))
    terminal_id = await _create_terminal(
        acp_session_context,
        config,
        tmp_path / "chatty.py",
        "import sys, time\nsys.stdout.write('pre-kill-marker')\n"
        "sys.stdout.flush()\ntime.sleep(120)\n",
    )
    process = acp_session_context.terminals[terminal_id]

    # Observe the retained marker before kill, then require the same snapshot.
    deadline = time.monotonic() + 10.0
    seen = ""
    while time.monotonic() < deadline and "pre-kill-marker" not in seen:
        live = await on_terminal_output(
            70,
            {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
            acp_session_context,
            config,
        )
        live_result = live.get("result")
        assert isinstance(live_result, dict)
        seen = str(live_result["output"])
        await asyncio.sleep(0.01)
    assert seen == "pre-kill-marker"

    killed = await on_terminal_kill(
        71,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert killed == jsonrpc_result(71, {})
    assert process.returncode is not None, "kill must stop the command"
    assert terminal_id in acp_session_context.terminals

    output = await on_terminal_output(
        72,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    output_result = output.get("result")
    assert isinstance(output_result, dict)
    assert output_result["output"] == "pre-kill-marker"
    assert output_result["truncated"] is False
    # A killed command has completed, so the status is present and describes how
    # it died. Which of the two fields carries that is platform-dependent, so the
    # assertion pins the exclusivity the schema requires rather than one host's
    # answer: a signal death has a null code and a named signal, a coded death
    # the reverse. Never both, never neither.
    exit_status = output_result["exitStatus"]
    assert isinstance(exit_status, dict)
    assert set(exit_status) == {"exitCode", "signal"}
    assert (exit_status["exitCode"] is None) != (exit_status["signal"] is None)
    if exit_status["signal"] is not None:
        assert isinstance(exit_status["signal"], str)

    waited = await on_terminal_wait_for_exit(
        73,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert waited == jsonrpc_result(73, exit_status)

    released = await on_terminal_release(
        74,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    assert released == jsonrpc_result(74, {})
    assert terminal_id not in acp_session_context.terminals
    # Released, the id takes the shared refusal path again.
    after = await on_terminal_output(
        75,
        {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
        acp_session_context,
        config,
    )
    error = after.get("error")
    assert isinstance(error, dict)
    assert error["code"] == AcpErrorCode.INVALID_PARAMS
