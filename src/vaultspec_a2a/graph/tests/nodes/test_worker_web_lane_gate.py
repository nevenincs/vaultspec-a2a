"""Real-subprocess proof that web grounding stays dark on an unproven lane.

No mocks: the worker node drives a real ACP subprocess (the protocol simulator)
through ``AcpChatModel``, and the assertions are made against the payload the CLI
actually received - the ``session/new`` allowlist and the ``session/prompt``
blocks. The declaration that would activate the capability is empty at landing, so
what these tests state is that the tree carries the wiring WITHOUT the capability:
an autonomous document role gets its read floor and nothing else, and its persona
still tells the model it has no online access.

The lane is the axis under test. The read floor is a property of the ROLE, so the
same autonomous researcher is driven on a lane with completed-turn proof, on one
without, and on a model that declares no lane at all: all three must land
identically, because none of them has web proof. A lane that read as web-capable
by accident - through an unresolvable provider string, say - would surface an
outward-reaching tool to a headless agent with no prompt in front of it.

A second, independent lock sits behind this one and is proven elsewhere: a native
tool name that has not declared its network-egress axis is refused at the
composition seam, so even a proof naming ``WebSearch`` today could not put it in an
allowlist (``providers/tests/test_acp_mcp_egress_axis.py``).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ....providers._acp_mcp import NATIVE_READ_TOOL_NAMES
from ....providers.lane_admission import web_tool_names_for
from ....team import load_agent_config
from ...nodes.worker import create_worker_node

if TYPE_CHECKING:
    from ....thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

# Lanes driven through the real spawn, none of which carries web proof: one with
# completed-turn proof (claude), one with none (kimi), and a model that declared no
# lane at all. Turn proof must not read as web proof, and an unidentified lane must
# deny rather than fall through.
UNPROVEN_WEB_LANES = ("claude", "kimi", None)

# Any built-in whose name marks it as reaching the network. Asserted as a pattern
# rather than an exact pair so a future built-in named `WebX` cannot slip into an
# allowlist here just because this test predates it.
_WEB_TOOL_NAME = re.compile(r"web", re.IGNORECASE)


def _make_state() -> TeamState:
    return {
        "active_agent": "researcher",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Research a topic")],
        "next": "",
        "thread_id": "test-thread-web-lane-gate",
        "token_usage": {},
    }


def _model(
    tmp_path: Path,
    *,
    provider: str | None,
    session_new: Path | None = None,
    session_prompt: Path | None = None,
):
    """A real ACP model on *provider*'s lane, recording what the CLI receives."""
    from ....providers.acp_chat_model import AcpChatModel

    command = [PYTHON_EXE, str(SIMULATOR_PATH), "--response", "researched"]
    if session_new is not None:
        command += ["--record-session-new", str(session_new)]
    if session_prompt is not None:
        command += ["--record-session-prompt", str(session_prompt)]
    return AcpChatModel(
        command=command,
        # Armed run: an env auth token so config-home isolation engages, which the
        # harness-armed spawn assertion requires. Production-faithful - a real armed
        # run always carries its lane token.
        env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
        workspace_root=str(tmp_path),
        provider=provider,
    )


def _allowed_tools(params: dict) -> list[str]:
    meta = params.get("_meta", {})
    return meta.get("claudeCode", {}).get("options", {}).get("allowedTools", [])


def _prompt_text(params: dict) -> str:
    """The prompt the CLI received, whitespace-normalised for phrase matching.

    The persona text is hard-wrapped in its preset, so a sentence that reads as one
    phrase spans a newline in the payload; matching against the raw text would miss
    the disclaimer and pass for the wrong reason.
    """
    joined = " ".join(
        block.get("text", "")
        for block in params.get("prompt", [])
        if block.get("type") == "text"
    )
    return " ".join(joined.split())


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", UNPROVEN_WEB_LANES)
async def test_an_unproven_lane_surfaces_no_web_tool_name(
    tmp_path: Path, provider: str | None
) -> None:
    """The CLI is permitted the read floor exactly, with no outward-reaching name."""
    record_file = tmp_path / "session_new.json"
    node = create_worker_node(
        model=_model(tmp_path, provider=provider, session_new=record_file),
        system_prompt="You are a researcher.",
        name="researcher",
        autonomous=True,
        role="researcher",
    )

    result = await node(_make_state())
    assert result["messages"][0].content == "researched"

    allowed = _allowed_tools(json.loads(record_file.read_text(encoding="utf-8")))
    # Two claims, deliberately separate. The first is the current dark state: the
    # floor, nothing more. The second binds the payload to the DECLARATION rather
    # than to a hardcoded empty, so the day a lane earns its proof this fails
    # unless the composition seam actually carries the names through - the
    # wired-but-dead failure mode, caught by the test that established darkness.
    assert [name for name in allowed if _WEB_TOOL_NAME.search(name)] == []
    assert allowed == [
        *NATIVE_READ_TOOL_NAMES,
        *web_tool_names_for(provider),
    ]


@pytest.mark.asyncio
async def test_an_unproven_lane_keeps_the_no_online_access_disclaimer(
    tmp_path: Path,
) -> None:
    """The real researcher persona reaches the model still disclaiming online reach.

    The persona text is loaded from the bundled preset rather than written here, so
    this fails the moment the shipped disclaimer is softened or dropped on a lane
    that has not earned the claim - which is the failure mode the per-lane proof
    gate exists to prevent: a capability claim the tools cannot back.
    """
    prompt_file = tmp_path / "session_prompt.json"
    persona = load_agent_config("vaultspec-researcher").persona.system_prompt
    node = create_worker_node(
        model=_model(tmp_path, provider="claude", session_prompt=prompt_file),
        system_prompt=persona,
        name="researcher",
        autonomous=True,
        role="researcher",
    )

    await node(_make_state())

    prompt = _prompt_text(json.loads(prompt_file.read_text(encoding="utf-8")))
    assert "no online access" in prompt
    # Guards the match above against a persona that says it has no online access
    # and then names a web tool anyway.
    assert "WebSearch" not in prompt
    assert "WebFetch" not in prompt
