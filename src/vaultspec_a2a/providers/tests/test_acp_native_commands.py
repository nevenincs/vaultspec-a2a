"""Real-process proofs for negotiated ACP native-command execution."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ...testing import simulator_command
from .._acp_types import NativeCommandOutcome
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from pathlib import Path

_COMMAND = "compact"
_COMMAND_PROMPT = "/compact focus"


def _model(tmp_path: Path, mode: str) -> AcpChatModel:
    """A model over a simulated agent that advertises, or withholds, one command."""
    advertised = [] if mode == "unsupported" else [_COMMAND]
    delay = ["--prompt-delay", "0.5"] if mode == "slow" else []
    return AcpChatModel(
        command=simulator_command(
            "--session-id",
            "session-1",
            "--advertise-commands",
            *advertised,
            "--expect-prompt",
            _COMMAND_PROMPT,
            "--response",
            "command-complete",
            *delay,
        ),
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
