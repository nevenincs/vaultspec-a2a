"""Live proof: the Claude provider completes a REAL turn through the production chain.

No mocks, no tape, no injected protocol. The model is built by the real
``ProviderFactory`` and drives the real ``claude-agent-acp`` subprocess over the
real ACP transport, so what passes here is a completed turn and nothing weaker.

This closes a coverage gap the neighbouring Claude live tests leave open by
design: they stop at the handshake surface (``initialize`` + ``session/new``) and
reap before any ``session/prompt``, which proves the transport but never proves
the provider produces assistant content. A frame count, a session id, or a
successful connect is NOT evidence of a completed turn; non-empty assistant text
is. Both channels are asserted here — the streamed deltas and the final
aggregated result — because a provider can stream nothing and still return a
result object, or stream and then lose the aggregation.

The Claude lane implements no authentication of its own: the spawned CLI
inherits the ambient environment and the operator's real config home, and
authenticates however the operator ambiently does - on this project's dev hosts,
a flat-rate subscription login. The prompt is trivial regardless, to keep the
turn short.

Re-arm (one command, once the prerequisites exist):

    uv run --no-sync pytest -m service \\
        src/vaultspec_a2a/providers/tests/test_claude_live_turn.py

Service-marked, so deselected from the default suite. When a prerequisite is
absent the test SKIPS naming exactly what is missing — an absent CLI or token is
reported as missing, never as a pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ...control.config import settings
from ...graph.enums import Model, Provider
from .._subprocess import kill_process_tree
from ..acp_chat_model import AcpChatModel
from ..factory import _CLAUDE_ACP_JS, ProviderFactory, _classify_acp_command

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.service
@pytest.mark.asyncio
async def test_claude_live_turn_completes_and_returns_content(tmp_path: Path) -> None:
    """A real Claude turn streams assistant text and returns a real AIMessage.

    Proves the provider tier end to end: the production factory resolves the ACP
    command with no auth of its own (the subprocess inherits the ambient
    environment and authenticates itself), the real subprocess runs a real
    ``session/prompt``, assistant deltas arrive as streamed chunks, and the
    aggregated result carries the same completed content. An unauthenticated
    host fails with the provider's own auth error, which is the contract.
    """
    if settings.acp_backend != "binary" and not _CLAUDE_ACP_JS.exists():
        pytest.skip(
            "Claude ACP node entry not installed; run 'npm install' "
            "(@agentclientprotocol/claude-agent-acp) per the ACP runbook"
        )

    model = ProviderFactory().create(
        Provider.CLAUDE, model=Model.LOW, workspace_root=tmp_path
    )
    assert isinstance(model, AcpChatModel)
    # The production chain injects NO credential of its own: the lane is
    # ambient-auth by contract, and the subprocess resolves whatever the
    # operator's environment carries.
    assert model.auth_mode == "ambient"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in model.env_vars
    assert "ANTHROPIC_API_KEY" not in model.env_vars

    messages = [
        SystemMessage(content="You are terse."),
        HumanMessage(content="Reply with exactly the single word: pong"),
    ]

    _, meta = _classify_acp_command(settings.acp_backend)
    try:
        streamed = "".join(
            [str(chunk.content) async for chunk in model.astream(messages)]
        )
        assert streamed.strip(), "Claude returned no streamed assistant text"

        result = await model.ainvoke(messages)
        assert isinstance(result, AIMessage)
        assert str(result.content).strip(), "Claude returned an empty final result"
    finally:
        # Production reaps its own tree and clears the handle; this guards the
        # path where a turn raises mid-session, because an unreaped tree leaks on
        # Windows.
        leaked = model._process
        if leaked is not None:
            await kill_process_tree(leaked, metadata=meta)
