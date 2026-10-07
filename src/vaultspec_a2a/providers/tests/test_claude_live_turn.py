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

The default Claude channel inherits the ambient environment and the operator's
real config home. The explicit oauth_token channel injects the configured
headless token. The prompt is trivial regardless, to keep the turn short.

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
from ...graph.enums import Provider
from ...testing import declared_lane_model_value
from .._factory_commands import _classify_acp_command, acp_launch_options
from .._subprocess import kill_process_tree
from ..acp_chat_model import AcpChatModel
from ..execution_modes import external_execution_mode
from ..factory import ProviderFactory, claude_auth_env

if TYPE_CHECKING:
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule


@pytest.mark.service
@pytest.mark.asyncio
async def test_claude_candidate_live_turn_completes_before_admission(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Earn a first turn proof before the production factory may admit this lane."""
    served, reason = await declared_lane_model_value(Provider.CLAUDE.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    command = _classify_acp_command(settings.acp_backend)
    env_vars, auth_mode = claude_auth_env()
    use_exec, launch_env = acp_launch_options(settings.acp_backend)
    model = AcpChatModel(
        command=list(command.argv),
        env_vars={**env_vars, **launch_env},
        desired_model=served,
        workspace_root=str(tmp_path),
        use_exec=use_exec,
        provider=Provider.CLAUDE.value,
        execution_mode=external_execution_mode(Provider.CLAUDE, settings.acp_backend),
        auth_mode=auth_mode,
    )
    result = await model.ainvoke(
        [
            SystemMessage(content="You are terse."),
            HumanMessage(content="Reply with exactly the single word: pong"),
        ]
    )
    assert isinstance(result, AIMessage)
    assert "pong" in str(result.content).lower()


@pytest.mark.service
@pytest.mark.asyncio
async def test_claude_live_turn_completes_and_returns_content(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """A real Claude turn streams assistant text and returns a real AIMessage.

    Proves the provider tier end to end: the production factory resolves the ACP
    command with no auth of its own (the subprocess inherits the ambient
    environment and authenticates itself), the real subprocess runs a real
    ``session/prompt``, assistant deltas arrive as streamed chunks, and the
    aggregated result carries the same completed content. An unauthenticated
    host fails with the provider's own auth error, which is the contract.
    """
    external_prerequisite("claude-acp-adapter")

    # The lane's turn PROOF runs on the model the operator declared. A
    # capability tier stood here until production stopped accepting one for an
    # external lane, and picking a served entry instead would make the proof
    # spend on a model nobody chose - the failure `testing/catalog_selection`
    # exists to make unrepresentable.
    served, reason = await declared_lane_model_value(Provider.CLAUDE.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    model = ProviderFactory().create(
        Provider.CLAUDE, model=served, workspace_root=tmp_path
    )
    assert isinstance(model, AcpChatModel)
    assert model.auth_mode == settings.claude_auth_channel
    if settings.claude_auth_channel == "subscription_login":
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in model.env_vars
    else:
        assert "CLAUDE_CODE_OAUTH_TOKEN" in model.env_vars
    assert "ANTHROPIC_API_KEY" not in model.env_vars

    messages = [
        SystemMessage(content="You are terse."),
        HumanMessage(content="Reply with exactly the single word: pong"),
    ]

    meta = _classify_acp_command(settings.acp_backend).metadata()
    try:
        streamed = "".join(
            [str(chunk.content) async for chunk in model.astream(messages)]
        )
        assert "pong" in streamed.lower(), "Claude streamed no model answer"

        result = await model.ainvoke(messages)
        assert isinstance(result, AIMessage)
        assert "pong" in str(result.content).lower(), "Claude returned no model answer"
    finally:
        # Production reaps its own tree and clears the handle; this guards the
        # path where a turn raises mid-session, because an unreaped tree leaks on
        # Windows.
        leaked = model._process
        if leaked is not None:
            await kill_process_tree(leaked, metadata=meta)
