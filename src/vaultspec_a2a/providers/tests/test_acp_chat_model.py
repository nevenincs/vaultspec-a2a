"""Live integration tests for AcpChatModel — the ACP JSON-RPC subprocess wrapper.

These tests exercise the full ACP protocol lifecycle against real CLI processes:
  initialize → session/new → session/prompt → session/update stream → end_turn

Requirements:
  - Claude: `claude-agent-acp` on PATH + CLAUDE_CODE_OAUTH_TOKEN in environment
  - Gemini: `gemini --experimental-acp` on PATH + ~/.gemini/oauth_creds.json
"""

from pathlib import Path

import pytest

from langchain_core.messages import HumanMessage

from ...core.config import settings
from ...utils.enums import MODEL_MAP, Model, Provider
from ..acp_chat_model import AcpChatModel
from ..factory import _CLAUDE_ACP_JS


_GEMINI_COMMAND = [
    "gemini",
    "--model",
    MODEL_MAP[Provider.GEMINI][Model.MID],
    "--experimental-acp",
]


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_claude_streaming() -> None:
    """End-to-end streaming test of AcpChatModel with the Claude ACP CLI.

    Verifies the full ACP protocol lifecycle fires correctly:
      - `initialize` handshake succeeds
      - `session/new` returns a sessionId
      - `session/prompt` streams `session/update` notifications
      - At least one `agent_message_chunk` is received and yielded as an AIMessageChunk
      - The assembled response contains the expected word
    """
    if not settings.claude_code_oauth_token:
        pytest.skip("CLAUDE_CODE_OAUTH_TOKEN not set — Claude ACP unavailable.")

    model = AcpChatModel(
        command=["node", str(_CLAUDE_ACP_JS)],
        env_vars={"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token},
    )

    messages = [
        HumanMessage(content="Reply with only the word 'Hello'. No other text.")
    ]

    chunks = []
    async for chunk in model.astream(messages):
        chunks.append(chunk.content)

    assert chunks, "No chunks received — ACP stream produced no output"
    full_response = "".join(str(c) for c in chunks)
    assert "hello" in full_response.lower(), (
        f"Expected 'hello' in streamed response, got: {full_response!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_gemini_streaming() -> None:
    """End-to-end streaming test of AcpChatModel with the Gemini ACP CLI.

    Verifies the full ACP protocol lifecycle with zero credential injection:
      - `initialize` handshake succeeds with no auth challenge
      - `session/new` returns a sessionId
      - `session/prompt` streams `session/update` notifications
      - At least one `agent_message_chunk` is received and yielded as an AIMessageChunk
      - The assembled response contains the expected word
    """
    model = AcpChatModel(
        command=_GEMINI_COMMAND,
        env_vars={},
    )

    messages = [
        HumanMessage(content="Reply with only the word 'Hello'. No other text.")
    ]

    chunks = []
    async for chunk in model.astream(messages):
        chunks.append(chunk.content)

    assert chunks, "No chunks received — Gemini ACP stream produced no output"
    full_response = "".join(str(c) for c in chunks)
    assert "hello" in full_response.lower(), (
        f"Expected 'hello' in streamed response, got: {full_response!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_claude_ainvoke() -> None:
    """Test that AcpChatModel.ainvoke accumulates the full streaming response.

    `ainvoke` goes through BaseChatModel._agenerate which collects _astream chunks.
    Verifies the aggregated AIMessage content is non-empty and correct.
    """
    if not settings.claude_code_oauth_token:
        pytest.skip("CLAUDE_CODE_OAUTH_TOKEN not set — Claude ACP unavailable.")

    model = AcpChatModel(
        command=["node", str(_CLAUDE_ACP_JS)],
        env_vars={"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token},
    )

    response = await model.ainvoke(
        [HumanMessage(content="Reply with only the word 'Hello'. No other text.")]
    )

    assert response.content
    assert "hello" in str(response.content).lower(), (
        f"Expected 'hello' in ainvoke response, got: {response.content!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_acp_gemini_ainvoke() -> None:
    """Test that Gemini AcpChatModel.ainvoke accumulates the full streaming response."""
    model = AcpChatModel(
        command=_GEMINI_COMMAND,
        env_vars={},
    )

    response = await model.ainvoke(
        [HumanMessage(content="Reply with only the word 'Hello'. No other text.")]
    )

    assert response.content
    assert "hello" in str(response.content).lower(), (
        f"Expected 'hello' in ainvoke response, got: {response.content!r}"
    )


# ---------------------------------------------------------------------------
# Unit tests: _auth_hint() and AcpErrorCode.UNAUTHENTICATED
# ---------------------------------------------------------------------------


class TestAuthHint:
    """Tests for AcpChatModel._auth_hint() provider detection."""

    def test_claude_hint_for_node_command(self) -> None:
        model = AcpChatModel(command=["node", "/path/to/cli.js"])
        hint = model._auth_hint()
        assert "claude login" in hint
        assert "CLAUDE_CODE_OAUTH_TOKEN" in hint

    def test_gemini_hint_for_gemini_command(self) -> None:
        model = AcpChatModel(command=["gemini", "--experimental-acp"])
        hint = model._auth_hint()
        assert "gemini" in hint
        assert "GEMINI_API_KEY" in hint

    def test_claude_hint_is_default_for_unknown_command(self) -> None:
        model = AcpChatModel(command=["unknown-cli", "--acp"])
        hint = model._auth_hint()
        assert "claude login" in hint

    def test_empty_command_returns_claude_hint(self) -> None:
        model = AcpChatModel(command=["node", "cli.js"])
        # Override command to empty to exercise fallback
        model.__dict__["command"] = []
        hint = model._auth_hint()
        assert "claude login" in hint


class TestAcpErrorCodeUnauthenticated:
    """Tests for the UNAUTHENTICATED AcpErrorCode member."""

    def test_unauthenticated_value(self) -> None:
        from ..acp_exceptions import AcpErrorCode
        assert AcpErrorCode.UNAUTHENTICATED == -32000

    def test_unauthenticated_is_int(self) -> None:
        from ..acp_exceptions import AcpErrorCode
        assert isinstance(AcpErrorCode.UNAUTHENTICATED, int)
