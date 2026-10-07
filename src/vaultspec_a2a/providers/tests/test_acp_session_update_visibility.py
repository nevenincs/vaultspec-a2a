"""ACP session notifications keep useful signals without logging raw payloads."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

import pytest

from .._acp_protocol import handle_session_update
from .._acp_types import AcpSessionContext

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_LOGGER = "vaultspec_a2a.providers._acp_protocol"
_OBSERVED_KINDS = (
    "async_task_progress",
    "async_task_spawned",
    "async_task_state_update",
    "compaction_summary_chunk",
    "compaction_update",
    "notice",
    "subagent_spawned",
    "subagent_state_update",
)


@pytest.mark.asyncio
async def test_adapter_session_updates_are_visible_without_payload_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The protocol logs adapter kinds and keeps the terminal usage separate."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdin.buffer.read()",
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
        prompt_id_ref=[],
        interrupt_exc=[],
    )

    async def send(update: JsonObject) -> None:
        await handle_session_update({"sessionId": "session-1", "update": update}, ctx)

    try:
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            await send(
                {
                    "sessionUpdate": "usage_update",
                    "used": 42,
                    "size": 200,
                    "_meta": {"_claude/rateLimit": "private-limit-detail"},
                }
            )
            await send(
                {
                    "sessionUpdate": "config_option_update",
                    "configOptions": [{"id": "model", "currentValue": "private-model"}],
                }
            )
            await send(
                {
                    "sessionUpdate": "session_info_update",
                    "_meta": {"airGoal": "private-user-goal"},
                }
            )
            for kind in _OBSERVED_KINDS:
                await send({"sessionUpdate": kind, "description": "private-text"})
            await send(
                {"sessionUpdate": "future_adapter_update", "text": "private-text"}
            )
            await send({"sessionUpdate": "bad\nkind", "text": "private-text"})
    finally:
        process.stdin.close()
        await process.wait()

    messages = [record.message for record in caplog.records if record.name == _LOGGER]
    assert "ACP context usage update: used=42 size=200" in messages
    assert "ACP config option update: 1 options received" in messages
    assert "ACP session info update received" in messages
    assert all(
        f"ACP session update observed: {kind}" in messages for kind in _OBSERVED_KINDS
    )
    assert "ACP unrecognized session update: future_adapter_update" in messages
    assert "ACP unrecognized session update: <invalid>" in messages
    assert "private-" not in "\n".join(messages)
    assert ctx.prompt_usage is None
    assert ctx.chunk_queue.empty()
