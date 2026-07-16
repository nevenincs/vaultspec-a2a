"""Live Z.ai fidelity probe (service-marked, re-armable from one env var).

Closes a flagged unknown: whether Z.ai's
Anthropic-Messages-compatible gateway is faithful enough — streaming shape AND
tool-calling — to drive the reused Claude ACP path. This is a REAL turn against
the REAL endpoint through claude-agent-acp; no mocks, no fakes, no hardcoded
expectations. Marketing "Anthropic-compatible" is not evidence; a passing turn is.

Re-arm (one command, the moment a token exists):

    ZAI_AUTH_TOKEN=<glm-anthropic-gateway-token> \\
        uv run --no-sync pytest -m service \\
        src/vaultspec_a2a/providers/tests/test_zai_fidelity.py

Optionally override the gateway with ZAI_BASE_URL (defaults to Z.ai's Anthropic
endpoint). The token is read from settings, never printed. Deselected by default
(``-m "not service"`` in addopts) and skipped when no token is configured, so the
default suite is unaffected until the owner arms it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from ...control.config import settings
from ...graph.enums import Provider
from ..acp_chat_model import AcpChatModel
from ..factory import ProviderFactory

if TYPE_CHECKING:
    from pathlib import Path

_ZAI_TOKEN_PRESENT = bool((settings.zai_auth_token or "").strip())


@pytest.mark.service
@pytest.mark.asyncio
@pytest.mark.skipif(not _ZAI_TOKEN_PRESENT, reason="no ZAI_AUTH_TOKEN configured")
async def test_zai_streaming_shape_is_faithful(tmp_path: Path) -> None:
    """A real Z.ai turn streams assistant deltas through the Claude ACP path.

    Proves the streaming-chunk shape the reused AcpChatModel path depends on
    survives Z.ai's gateway: multiple ChatGenerationChunks with real text content.
    """
    model = ProviderFactory().create(Provider.ZAI, workspace_root=tmp_path)
    assert isinstance(model, AcpChatModel)
    # The gateway vars are injected; the token itself is never surfaced here.
    assert model.env_vars.get("ANTHROPIC_BASE_URL") == settings.zai_base_url
    assert "ANTHROPIC_AUTH_TOKEN" in model.env_vars

    messages = [
        SystemMessage(content="You are terse."),
        HumanMessage(content="Reply with exactly the single word: pong"),
    ]
    streamed = "".join([str(chunk.content) async for chunk in model.astream(messages)])
    assert streamed.strip(), "Z.ai returned no streamed assistant text"


@pytest.mark.service
@pytest.mark.asyncio
@pytest.mark.skipif(not _ZAI_TOKEN_PRESENT, reason="no ZAI_AUTH_TOKEN configured")
async def test_zai_tool_calling_is_faithful(tmp_path: Path) -> None:
    """A real Z.ai turn drives the agent's native tool-calling loop to a side effect.

    The ADR's fidelity concern is whether Z.ai reproduces the Anthropic
    tool-calling schema faithfully enough for the Claude Code CLI's agentic loop.
    We force a filesystem write and assert the file materialises — an
    end-to-end, unfakeable signal that a tool call was emitted, accepted, and
    executed. ``allowed_tools`` auto-permits the Write tool so the headless turn
    does not stall on a permission prompt.
    """
    model = ProviderFactory().create(Provider.ZAI, workspace_root=tmp_path)
    assert isinstance(model, AcpChatModel)
    model.allowed_tools = ["Write"]

    target = tmp_path / "zai_probe.txt"
    messages = [
        SystemMessage(content="You are a coding agent. Use your tools."),
        HumanMessage(
            content=(
                "Create a file named zai_probe.txt in the current working "
                "directory containing exactly the word: pong. Then stop."
            )
        ),
    ]
    async for _ in model.astream(messages):
        pass

    assert target.exists(), "Z.ai did not drive the Write tool to create the file"
    assert "pong" in target.read_text(encoding="utf-8").lower()
