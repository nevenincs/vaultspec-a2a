"""What an ACP child said before it died survives its death, redacted.

Driven against a real subprocess that answers the handshake, opens a session, then
writes to standard error and exits mid-turn - the shape every startup failure and
refused login takes on this lane. What is asserted is the diagnostic a caller
actually receives, not the one the code is expected to assemble.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from .._subprocess import STDERR_TAIL_LINES
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpError
from ._acp_frames import SESSION_MODES

if TYPE_CHECKING:
    from pathlib import Path

# A credential-shaped line, because the redaction that matters is the one on the
# path a real child takes: provider CLIs report their configuration when they
# fail, and configuration is where the tokens are.
_SECRET_LINE = "ANTHROPIC_AUTH_TOKEN=sk-super-secret"
_FATAL_LINE = "fatal: no credentials available"
_SESSION_ID = "sess-dying"


def _dying_agent(stderr_lines: list[str]) -> str:
    """An ACP responder that opens a session, then dies with *stderr_lines*."""
    return f"""
import json, sys

def reply(msg_id, result):
    sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg_id, "result": result}}))
    sys.stdout.write("\\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        reply(message["id"], {{
            "protocolVersion": 1,
            "agentCapabilities": {{}},
            "authMethods": [],
        }})
    elif method == "session/new":
        reply(message["id"], {{
            "sessionId": {json.dumps(_SESSION_ID)},
            "modes": {json.dumps(SESSION_MODES)},
        }})
    elif method == "session/prompt":
        for text in {json.dumps(stderr_lines)}:
            print(text, file=sys.stderr)
        sys.stderr.flush()
        break
"""


def _model(tmp_path: Path, stderr_lines: list[str]) -> AcpChatModel:
    script = tmp_path / "dying_agent.py"
    script.write_text(_dying_agent(stderr_lines), encoding="utf-8")
    return AcpChatModel(
        command=[sys.executable, str(script)],
        env_vars={},
        workspace_root=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_an_early_exit_carries_the_redacted_tail_on_its_error(
    tmp_path: Path,
) -> None:
    """The failure a caller catches names what the child said, with no secret."""
    model = _model(tmp_path, [_SECRET_LINE, _FATAL_LINE])

    with pytest.raises(AcpError) as failure:
        async for _ in model.astream([HumanMessage(content="go")]):
            pass

    message = str(failure.value)
    assert _FATAL_LINE in message
    assert "sk-super-secret" not in message
    assert "<redacted>" in message


@pytest.mark.asyncio
async def test_the_tail_is_reported_at_warning_with_the_session_it_belonged_to(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A run at the default level sees the diagnostic and the provider session.

    Both were previously invisible: the lines went to DEBUG under an INFO default
    and the session id was read off the wire and dropped, so a failed turn left
    nothing to correlate with the transcript the CLI wrote.
    """
    model = _model(tmp_path, [_SECRET_LINE, _FATAL_LINE])

    with (
        caplog.at_level(logging.INFO, logger="vaultspec_a2a.providers"),
        pytest.raises(AcpError),
    ):
        async for _ in model.astream([HumanMessage(content="go")]):
            pass

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert any(_FATAL_LINE in text for text in warnings), warnings
    assert not any("sk-super-secret" in text for text in warnings)

    opened = [
        vars(record)
        for record in caplog.records
        if record.message == "ACP session opened"
    ]
    assert opened, caplog.messages
    assert opened[0]["session_id"] == _SESSION_ID


@pytest.mark.asyncio
async def test_the_retained_tail_is_bounded(tmp_path: Path) -> None:
    """A chatty child cannot turn a diagnostic into unbounded retention."""
    overflow = STDERR_TAIL_LINES * 2
    model = _model(tmp_path, [f"line-{index}" for index in range(overflow)])

    with pytest.raises(AcpError) as failure:
        async for _ in model.astream([HumanMessage(content="go")]):
            pass

    message = str(failure.value)
    # One line for the failure's own sentence, then at most the retained tail.
    assert len(message.splitlines()) <= STDERR_TAIL_LINES + 1
    # What is kept is the END of the stream: the last thing a child says is the
    # part that explains why it stopped.
    assert f"line-{overflow - 1}" in message
    assert "line-0\n" not in message
