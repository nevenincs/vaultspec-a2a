"""Real-process proofs for retained ACP terminal output and drain ownership."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import pytest

from ...utils._process_tree import pid_is_live
from .._acp_rpc_terminal_handlers import (
    on_terminal_create,
    on_terminal_output,
    on_terminal_release,
    on_terminal_wait_for_exit,
    release_owned_terminal,
)
from .._acp_terminal_output import MAX_TERMINAL_OUTPUT_BYTES
from ..acp_chat_model import AcpChatModel
from ._terminal_process import retain_terminal_process

if TYPE_CHECKING:
    from pathlib import Path

    from .._acp_types import AcpModelConfig, AcpSessionContext
    from .._json_contract import JsonObject, JsonValue


async def _create(
    root: Path,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    body: str,
    cap: JsonValue,
) -> str:
    script = root / "producer.py"
    script.write_text(body, encoding="utf-8")
    assert cap is None or isinstance(cap, int)
    limit = MAX_TERMINAL_OUTPUT_BYTES if cap is None else cap
    return await retain_terminal_process(ctx, root, [str(script)], limit)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cap", "expected"), [(0, ""), (1, "Z"), (4, "Z"), (5, "🙂Z"), (6, "A🙂Z")]
)
async def test_byte_cap_retains_complete_utf8_tail_and_stable_snapshots(
    tmp_path: Path, acp_session_context: AcpSessionContext, cap: int, expected: str
) -> None:
    ctx = acp_session_context
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    terminal_id = await _create(
        tmp_path,
        ctx,
        config,
        "import sys\nsys.stdout.buffer.write('A🙂Z'.encode())\n",
        cap,
    )
    params: JsonObject = {"sessionId": ctx.session_id, "terminalId": terminal_id}
    waited = await on_terminal_wait_for_exit(2, params, ctx, config)
    assert waited["result"] == {"exitCode": 0, "signal": None}
    for rpc_id in (3, 4):
        result = (await on_terminal_output(rpc_id, params, ctx, config))["result"]
        assert result == {
            "output": expected,
            "truncated": cap < 6,
            "exitStatus": {"exitCode": 0, "signal": None},
        }
        assert len(expected.encode("utf-8")) <= cap
    await on_terminal_release(5, params, ctx, config)
    assert not ctx.terminals and not ctx.terminal_outputs


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [-1, True, False, 4.0, "4", 2**64, float("inf")])
async def test_invalid_cap_is_refused_before_spawn(
    tmp_path: Path, acp_session_context: AcpSessionContext, cap: JsonValue
) -> None:
    script = tmp_path / "must_not_run.py"
    script.write_text("from pathlib import Path\nPath('spawned').touch()\n", "utf-8")
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    response = await on_terminal_create(
        1,
        {
            "sessionId": acp_session_context.session_id,
            "command": sys.executable,
            "args": [str(script)],
            "outputByteLimit": cap,
        },
        acp_session_context,
        config,
    )
    assert "error" in response and "result" not in response
    assert not acp_session_context.terminals
    assert not acp_session_context.terminal_outputs
    assert not (tmp_path / "spawned").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [0, 4, None])
async def test_both_pipes_drain_without_output_polling_and_retain_bounded_output(
    tmp_path: Path, acp_session_context: AcpSessionContext, cap: int | None
) -> None:
    ctx = acp_session_context
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    terminal_id = await _create(
        tmp_path,
        ctx,
        config,
        "import sys\nfrom pathlib import Path\n"
        "for stream in (sys.stdout.buffer, sys.stderr.buffer):\n"
        f"    stream.write(b'x' * {32 * MAX_TERMINAL_OUTPUT_BYTES})\n"
        "    stream.flush()\n"
        "Path('finished').touch()\n",
        cap,
    )
    params: JsonObject = {
        "sessionId": ctx.session_id,
        "terminalId": terminal_id,
        "timeout": 15,
    }
    waited = await on_terminal_wait_for_exit(2, params, ctx, config)
    assert waited.get("result") == {"exitCode": 0, "signal": None}, waited
    assert (tmp_path / "finished").is_file()
    expected_size = MAX_TERMINAL_OUTPUT_BYTES if cap is None else cap
    result = (await on_terminal_output(3, params, ctx, config))["result"]
    assert isinstance(result, dict)
    assert result["output"] == "x" * expected_size
    assert result["truncated"] is True
    await release_owned_terminal(terminal_id, ctx)
    assert not ctx.terminals and not ctx.terminal_outputs


@pytest.mark.asyncio
async def test_incremental_utf8_handles_split_sequences_and_malformed_bytes(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    ctx = acp_session_context
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    terminal_id = await _create(
        tmp_path,
        ctx,
        config,
        "import sys, time\n"
        "sys.stdout.buffer.write(b'A' * 65535 + b'\\xe2')\n"
        "sys.stdout.buffer.flush()\ntime.sleep(.05)\n"
        "sys.stdout.buffer.write(b'\\x82\\xacB\\xff\\xe2')\n",
        20,
    )
    params: JsonObject = {"sessionId": ctx.session_id, "terminalId": terminal_id}
    await on_terminal_wait_for_exit(2, params, ctx, config)
    result = (await on_terminal_output(3, params, ctx, config))["result"]
    assert isinstance(result, dict)
    assert result["output"] == "A" * 10 + "€B��"
    assert result["truncated"] is True
    assert len(str(result["output"]).encode("utf-8")) == 20


@pytest.mark.asyncio
async def test_release_cancellation_joins_drains_and_reaps_terminal(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    ctx = acp_session_context
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    terminal_id = await _create(
        tmp_path,
        ctx,
        config,
        "import sys, time\nsys.stdout.write('ready')\n"
        "sys.stdout.flush()\ntime.sleep(120)\n",
        4,
    )
    state = ctx.terminal_outputs[terminal_id]
    async with asyncio.timeout(5):
        while not state.output:
            await asyncio.sleep(0.01)
    released = asyncio.create_task(release_owned_terminal(terminal_id, ctx))
    await asyncio.sleep(0)
    released.cancel()
    with pytest.raises(asyncio.CancelledError):
        await released
    assert state.process.returncode is not None
    assert all(task.done() for task in state._tasks)
    assert not ctx.terminals and not ctx.terminal_outputs
    before = state.output
    await asyncio.sleep(0.05)
    assert state.output == before


@pytest.mark.asyncio
async def test_stdout_and_stderr_use_independent_utf8_decoders(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    ctx = acp_session_context
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    terminal_id = await _create(
        tmp_path,
        ctx,
        config,
        "import sys\nsys.stdout.buffer.write(b'\\xe2')\n"
        "sys.stdout.buffer.flush()\nsys.stderr.buffer.write('🙂'.encode())\n"
        "sys.stderr.buffer.flush()\nsys.stdin.readline()\n"
        "sys.stdout.buffer.write(b'\\x82\\xac')\n",
        7,
    )
    state = ctx.terminal_outputs[terminal_id]
    async with asyncio.timeout(5):
        while state.output != "🙂":
            await asyncio.sleep(0.01)
    process = ctx.terminals[terminal_id]
    assert process.stdin is not None
    process.stdin.write(b"finish\n")
    await process.stdin.drain()
    params: JsonObject = {"sessionId": ctx.session_id, "terminalId": terminal_id}
    await on_terminal_wait_for_exit(2, params, ctx, config)
    result = (await on_terminal_output(3, params, ctx, config))["result"]
    assert result == {
        "output": "🙂€",
        "truncated": False,
        "exitStatus": {"exitCode": 0, "signal": None},
    }


@pytest.mark.asyncio
async def test_exited_root_with_descendant_pipe_does_not_block_snapshot_or_release(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    ctx = acp_session_context
    config = AcpChatModel(
        command=[sys.executable], workspace_root=str(tmp_path)
    )._config
    terminal_id = await _create(
        tmp_path,
        ctx,
        config,
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(120)'])\nprint(child.pid, flush=True)\n",
        None,
    )
    state = ctx.terminal_outputs[terminal_id]
    async with asyncio.timeout(10):
        while not state.output.strip() or state.process.returncode is None:
            await asyncio.sleep(0.01)
    descendant = int(state.output.strip())
    assert pid_is_live(descendant)
    params: JsonObject = {"sessionId": ctx.session_id, "terminalId": terminal_id}
    async with asyncio.timeout(3):
        result = (await on_terminal_output(2, params, ctx, config))["result"]
        assert isinstance(result, dict)
        assert result["output"] == state.output
        assert result["exitStatus"] == {"exitCode": 0, "signal": None}
        waited = await on_terminal_wait_for_exit(3, params, ctx, config)
        assert waited["result"] == {"exitCode": 0, "signal": None}
    await on_terminal_release(4, params, ctx, config)
    assert not pid_is_live(descendant)
    assert all(task.done() for task in state._tasks)
    assert not ctx.terminals and not ctx.terminal_outputs
