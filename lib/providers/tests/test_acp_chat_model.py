"""Live integration tests for AcpChatModel — the ACP JSON-RPC subprocess wrapper.

These tests exercise the full ACP protocol lifecycle against real CLI processes:
  initialize → session/new → session/prompt → session/update stream → end_turn

Requirements:
  - Claude: `claude-agent-acp` on PATH + CLAUDE_CODE_OAUTH_TOKEN in environment
  - Gemini: `gemini --experimental-acp` on PATH + ~/.gemini/oauth_creds.json
"""

import pytest

from langchain_core.messages import HumanMessage

from ...core.config import settings
from ...utils.enums import Model
from ..acp_chat_model import AcpChatModel

_GEMINI_COMMAND = ["gemini", "--model", Model.GEMINI_3_FLASH_PREVIEW.value, "--experimental-acp"]


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
        command=["claude-agent-acp"],
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


@pytest.mark.asyncio
async def test_acp_claude_ainvoke() -> None:
    """Test that AcpChatModel.ainvoke accumulates the full streaming response.

    `ainvoke` goes through BaseChatModel._agenerate which collects _astream chunks.
    Verifies the aggregated AIMessage content is non-empty and correct.
    """
    if not settings.claude_code_oauth_token:
        pytest.skip("CLAUDE_CODE_OAUTH_TOKEN not set — Claude ACP unavailable.")

    model = AcpChatModel(
        command=["claude-agent-acp"],
        env_vars={"CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token},
    )

    response = await model.ainvoke(
        [HumanMessage(content="Reply with only the word 'Hello'. No other text.")]
    )

    assert response.content
    assert "hello" in str(response.content).lower(), (
        f"Expected 'hello' in ainvoke response, got: {response.content!r}"
    )


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
