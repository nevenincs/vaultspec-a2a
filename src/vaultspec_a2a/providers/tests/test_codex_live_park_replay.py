"""The served-lane proof for the Codex abandon outcome: park, abandon, replay.

This is the one credential-run step that lets the abandon outcome ship to a
served profile. Construction coverage does not qualify and neither does the
stdio stand-in: the claim is about the real ``codex app-server``, so the only
thing that can establish it is a real supervised turn on a real binary inside
the lane's admitted completed-turn range.

What it proves, in one run:

1. A supervised Codex turn reaches a real MCP tool-approval elicitation. The
   gated surface is the harness search server, which production serves WITHOUT
   ``default_tools_approval_mode = "auto"`` precisely because its calls choose
   the project they address - so every call is elicited and decided by the run's
   permission rung. That is the production supervised shape, not a test one.
2. The human rung suspends the run, the worker answers the elicitation with the
   lane's abandon action, and the app-server accepts it and ends the session
   cleanly: the suspension is what leaves the turn, rather than a protocol
   error, a timeout or an end-of-stream failure.
3. After the human answer, the replayed turn completes with real model output.
   The replay is a fresh invocation whose rung already holds the answer, which is
   exactly what the worker node does: it re-runs from the top and finds its
   earlier approvals by request id instead of in interrupt order.

The graph is deliberately not in the loop. The rung is handed to the provider as
a callback that cannot reach graph state, so what the provider can observe is the
callback raising the real ``GraphInterrupt`` and, on the replay, returning the
recorded answer. The interrupt plumbing either side of that callback is proven on
the deterministic lane; what no fixture lane can prove is that THIS binary
accepts the abandon action and still serves the replayed turn.

Never run this to satisfy a suite. It spends an operator credential on a real
model turn, so it is ``service``-marked and gated on the same two prerequisites
every live Codex turn uses - the CLI and a persisted login - and it reports the
resolved binary being outside the admitted range as a missing prerequisite rather
than running anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from ...graph.enums import Provider
from ...testing import declared_lane_model_value
from .._acp_mcp import compose_harness_mcp_servers
from .._codex_permission import ACCEPT_ACTION
from ..codex_chat_model import CodexChatModel
from ..factory import ProviderFactory, codex_binary_proof_reason
from ..lane_admission import PROVEN_TURN_LANES

if TYPE_CHECKING:
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule
    from .._acp_types import PermissionCallback
    from .._json_contract import JsonObject

#: The harness server whose calls production elicits rather than pre-approves.
_RAG_SERVER = "vaultspec-rag"

#: The tool the prompt asks for, from that server's declared read surface.
_RAG_TOOL = "search_codebase"

#: What the model is asked to say once the gated call has come back. Real output
#: generated after the human answer is what "the replayed turn completes" means.
_COMPLETION_TOKEN = "PARKPROOF"


@pytest.mark.service
@pytest.mark.asyncio
async def test_codex_live_park_abandons_then_the_replayed_turn_completes(
    tmp_path: Path, external_prerequisite: ExternalPrerequisiteRule
) -> None:
    """A live supervised Codex turn parks, abandons, and then replays to output."""
    external_prerequisite("codex-cli")
    external_prerequisite("codex-credential")
    served, reason = await declared_lane_model_value(Provider.CODEX.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)

    model = ProviderFactory().create(
        Provider.CODEX, model=served, workspace_root=tmp_path
    )
    assert isinstance(model, CodexChatModel)

    # The proof binds to a binary identity, so a resolved launcher outside the
    # admitted range cannot earn it. Reported as a missing prerequisite: the
    # binary is present and is the wrong one, which is not a defect in the lane.
    proof = PROVEN_TURN_LANES[Provider.CODEX]
    out_of_range = codex_binary_proof_reason(
        model.provider_command, workspace_root=tmp_path
    )
    if out_of_range is not None:
        external_prerequisite.absent(
            "codex-cli",
            f"the resolved Codex binary is not admitted by the completed-turn "
            f"proof ({proof.floor} <= version < {proof.ceiling_exclusive}): "
            f"{out_of_range.value}",
        )

    supervised = compose_harness_mcp_servers(
        model, [_RAG_SERVER], project_root=str(tmp_path), lane=Provider.CODEX.value
    )
    assert isinstance(supervised, CodexChatModel)

    asked: list[tuple[str, list[str]]] = []

    def rung(answer: str | None) -> PermissionCallback:
        """Build the human rung for one turn: ``None`` parks, a string answers.

        The parking arm raises the real ``GraphInterrupt`` a supervised rung
        raises, and the answering arm returns the recorded answer the way a
        replayed turn's callback resolves a request it already has.
        """

        async def callback(
            tool_name: str, _args: JsonObject, options: list[JsonObject]
        ) -> str:
            asked.append(
                (tool_name, [str(option.get("optionId")) for option in options])
            )
            if answer is None:
                raise GraphInterrupt(
                    (Interrupt(value={"tool": tool_name}, id="live-park-1"),)
                )
            return answer

        return callback

    messages = [
        SystemMessage(content="You are terse and you use the tools you are given."),
        HumanMessage(
            content=(
                f"Call the {_RAG_TOOL} tool with project_root set to "
                f"{tmp_path} and query set to 'anything'. You must call it "
                "before you answer. Once it returns, reply with exactly this "
                f"word and nothing else: {_COMPLETION_TOKEN}"
            )
        ),
    ]

    parked = supervised.model_copy(update={"permission_callback": rung(None)})
    with pytest.raises(GraphInterrupt) as suspension:
        await parked.ainvoke(messages)

    assert asked, (
        "the supervised turn never reached the tool-approval rung, so nothing "
        "parked: the model did not call the gated tool, or the harness server "
        "was pre-approved instead of elicited"
    )
    tool_name, offered = asked[0]
    assert tool_name == f"mcp__{_RAG_SERVER}__{_RAG_TOOL}"
    assert offered == ["accept", "decline"]
    assert suspension.value.args[0][0].id == "live-park-1"

    # The replay: a fresh invocation whose rung already holds the human answer,
    # exactly as the re-run worker node resolves a request it has an answer for.
    answered = supervised.model_copy(
        update={"permission_callback": rung(ACCEPT_ACTION)}
    )
    result = await answered.ainvoke(messages)

    assert isinstance(result, AIMessage)
    assert len(asked) > 1, "the replayed turn did not reach the gated call again"
    output = str(result.content).strip()
    assert output, (
        "the replayed turn produced no model output, so the abandoned session "
        "did not leave the lane able to serve the answered turn"
    )
    assert _COMPLETION_TOKEN.casefold() in output.casefold(), (
        f"the replayed turn completed without the requested token: {output!r}"
    )
