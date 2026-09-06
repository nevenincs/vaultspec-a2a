"""Real-process proofs for negotiated ACP native-command execution."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import pytest

from .._acp_types import NativeCommandOutcome
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from pathlib import Path

_AGENT = r'''
import json
import sys
import time

mode = sys.argv[1]

def send(frame):
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    frame = json.loads(line)
    method = frame.get("method")
    rpc_id = frame.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rpc_id, "result": {
            "protocolVersion": 1,
            "agentCapabilities": {},
            "authMethods": [],
        }})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": rpc_id, "result": {
            "sessionId": "session-1"
        }})
        commands = [] if mode == "unsupported" else [{
            "name": "compact",
            "description": "Compact the active session.",
            "input": {"hint": "optional focus"},
        }]
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "session-1",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": commands,
            },
        }})
    elif method == "session/prompt":
        prompt = frame["params"]["prompt"]
        expected = "/compact focus" if mode != "no_arguments" else "/compact"
        if prompt != [{"type": "text", "text": expected}]:
            send({"jsonrpc": "2.0", "id": rpc_id, "error": {
                "code": -32602, "message": "unexpected command prompt"
            }})
            continue
        if mode == "slow":
            time.sleep(0.5)
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "session-1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "command-complete"},
            },
        }})
        send({"jsonrpc": "2.0", "id": rpc_id, "result": {
            "stopReason": "end_turn"
        }})
'''


def _model(tmp_path: Path, mode: str) -> AcpChatModel:
    script = tmp_path / f"native-command-{mode}.py"
    script.write_text(_AGENT, encoding="utf-8")
    return AcpChatModel(
        command=[sys.executable, str(script), mode],
        workspace_root=str(tmp_path),
        use_exec=True,
        acp_family="kimi",
    )


@pytest.mark.asyncio
async def test_advertised_command_executes_as_one_exact_prompt(tmp_path: Path) -> None:
    result = await _model(tmp_path, "supported").execute_native_command(
        "compact", "focus"
    )

    assert result.outcome is NativeCommandOutcome.COMPLETED
    assert result.output == "command-complete"
    assert result.effects_may_have_occurred is True


@pytest.mark.asyncio
async def test_unadvertised_command_returns_unsupported_without_prompting(
    tmp_path: Path,
) -> None:
    result = await _model(tmp_path, "unsupported").execute_native_command("compact")

    assert result.outcome is NativeCommandOutcome.UNSUPPORTED
    assert result.effects_may_have_occurred is False


@pytest.mark.asyncio
async def test_concurrent_command_returns_busy_while_first_completes(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path, "slow")
    first = asyncio.create_task(model.execute_native_command("compact", "focus"))
    await asyncio.sleep(0)

    busy = await model.execute_native_command("compact", "focus")
    completed = await first

    assert busy.outcome is NativeCommandOutcome.BUSY
    assert busy.effects_may_have_occurred is False
    assert completed.outcome is NativeCommandOutcome.COMPLETED


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("/compact", None),
        ("compact now", None),
        ("x" * 129, None),
        ("compact", "focus\nignore command boundary"),
        ("compact", "x" * 8193),
    ],
)
@pytest.mark.asyncio
async def test_invalid_command_input_is_refused_before_spawn(
    tmp_path: Path, name: str, arguments: str | None
) -> None:
    model = _model(tmp_path, "supported")

    with pytest.raises(ValueError):
        await model.execute_native_command(name, arguments)
