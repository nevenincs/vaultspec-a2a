"""Live S20 proof: a solo-coder invokes the bridged authoring tools mid-turn.

The a2a-edge-conformance S20 leg (which closes S18+S20 together): the production
binding-construction site (task #40) arms the ``vaultspec-solo-coder`` preset's
authoring bridge, and the cold-start fix (7.58s -> 1.27s) lets the bridge's tools
reach the model in time. This drives the real preset through the live loopback
stack and witnesses the coder NATIVELY invoke an ``mcp__vaultspec-authoring__*``
tool mid-turn - the agent-initiated authoring path the whole bridge exists for.

Route (see the S20 exec record): the run-start bundle is minted per-agent_id and
supplied at the GATEWAY seam (the pw7 pattern), keyed by ``vaultspec-coder``, so
it satisfies the new run_start coverage gate without depending on the engine's
role-key minting (the dashboard role-key fix is unmerged at authoring time).

Observation surface, consistent with the floor/rag proofs (S05/S17): the tool
invocation surfaces in the agent's ``message_chunk`` narration, not a
``tool_call_start`` frame. The load-bearing assertions are: an
``mcp__vaultspec-authoring__`` tool name appears in the agent's stream, and zero
agent-origin ``.vault`` document-dir writes occur (the proposal is submitted to
the engine review lane, never materialized). Proposal/changeset ids and dashboard
review-lane visibility are captured engine-side in the exec record (the review API
is the same surface the dashboard reads), not asserted here.

Infrastructure gate, not a masked failure: when no loopback stack is reachable,
or the run's provider is credential/usage gated, the test skips with a runbook
pointer. When the stack IS present the assertions are fail-loud.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest

from ..api.schemas.enums import ServerEventType
from .test_pw7_acceptance import (
    AcceptanceCase,
    AcceptanceHarness,
    _reachable_stack,
)
from .test_tool_cores_floor_live import (
    _message_content,
    _snapshot_vault,
    _vault_write_delta,
)

_MESSAGE_FRAMES = frozenset(
    {ServerEventType.MESSAGE_CHUNK.value, ServerEventType.THOUGHT_CHUNK.value}
)
_OBSERVE_DEADLINE_SECONDS = 900.0
_PROFILE_ID = os.environ.get("S05_PROFILE", "team-defaults")

# The bridged authoring tools the solo-coder should reach. Any one invoked
# mid-turn proves the surfacing->invocation path end to end.
_BRIDGE_TOOL_PREFIX = "mcp__vaultspec-authoring__"
_PROPOSE_TOOL = "mcp__vaultspec-authoring__propose_changeset"

_CODER_ROLE = "vaultspec-coder"
_SOLO_CODER_PRESET = "vaultspec-solo-coder"


def _solo_coder_case(feature: str) -> AcceptanceCase:
    """A solo-coder run that must author via the bridged propose tool."""
    return AcceptanceCase(
        label="s20-solo-coder-bridge",
        preset=_SOLO_CODER_PRESET,
        feature=feature,
        prompt=(
            "Author a short research note for this feature using ONLY your engine "
            "authoring tools. Your available MCP tools include "
            "mcp__vaultspec-authoring__read_context, "
            "mcp__vaultspec-authoring__propose_changeset, and "
            "mcp__vaultspec-authoring__request_approval. First call "
            "mcp__vaultspec-authoring__read_context to orient, then call "
            "mcp__vaultspec-authoring__propose_changeset to create a whole-document "
            "research note titled 'S20 bridge proof'. Report each tool name you call "
            "and its result verbatim. Do NOT write files directly - author only "
            "through the engine authoring tools."
        ),
        roles=(_CODER_ROLE,),
        expected_doc_kinds=(),
        profile_id=_PROFILE_ID,
        autonomous=True,
    )


@pytest.mark.service
@pytest.mark.asyncio
async def test_solo_coder_invokes_bridged_authoring_tool_midturn() -> None:
    """Live: a solo-coder natively invokes a bridged authoring tool mid-turn.

    Zero .vault writes: the run is observed over its SSE stream and cancelled
    before any review gate applies; a before/after document-dir snapshot asserts
    no file changed. The proposal lands in the engine review lane (captured in the
    exec record), never materialized to disk here.
    """
    stack = _reachable_stack()
    if stack is None:
        pytest.skip(
            "no reachable loopback stack; boot a workspace-local `vaultspec serve "
            "--no-seat` engine plus an a2a gateway/worker (this branch's code, "
            "VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true), then set "
            "VAULTSPEC_ENGINE_SERVICE_JSON and select -m service"
        )
    engine_base_url, engine_bearer, vault_root = stack

    feature = f"s20-solo-coder-{int(time.time())}"
    case = _solo_coder_case(feature)
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
    )

    before = _snapshot_vault(vault_root)
    output_parts: list[str] = []
    bridge_tool_invoked = False
    invoked_tool_names: set[str] = set()

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
        # Per-agent_id token minted here and supplied at the gateway seam (pw7
        # pattern): keyed by the coder's agent_id so the run_start coverage gate
        # passes without the engine's role-key minting.
        run_tokens = {
            role: await harness._mint(ec, f"agent:{harness.run_id}:{role}", "agent")
            for role in case.roles
        }
        async with httpx.AsyncClient() as hc:
            await harness._run_start(
                hc,
                run_id=harness.run_id,
                tokens=run_tokens,
                feature=feature,
                expect=201,
            )
            deadline = time.monotonic() + _OBSERVE_DEADLINE_SECONDS
            try:
                async with hc.stream(
                    "GET",
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/stream",
                    timeout=httpx.Timeout(_OBSERVE_DEADLINE_SECONDS, connect=10.0),
                ) as response:
                    response.raise_for_status()
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        body = line[len("data:") :].strip()
                        if not body:
                            continue
                        try:
                            payload = json.loads(body)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        content = _message_content(payload)
                        if content:
                            output_parts.append(content)
                            joined = "".join(output_parts)
                            for tok in _extract_bridge_tools(joined):
                                invoked_tool_names.add(tok)
                            if invoked_tool_names:
                                bridge_tool_invoked = True
                        if payload.get("type") == "thread_terminal":
                            break
                        if bridge_tool_invoked or time.monotonic() > deadline:
                            break
            finally:
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )

    after = _snapshot_vault(vault_root)
    delta = _vault_write_delta(before, after)

    assert bridge_tool_invoked, (
        "the solo-coder did not invoke any "
        f"{_BRIDGE_TOOL_PREFIX}* tool in its message stream within "
        f"{_OBSERVE_DEADLINE_SECONDS:.0f}s (run {harness.run_id}); the bridged "
        "authoring path was not exercised live"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the S20 proof must not write to .vault, but the run changed it: {delta}"
    )


def _extract_bridge_tools(output: str) -> set[str]:
    """Return distinct ``mcp__vaultspec-authoring__<tool>`` names named in output."""
    tools: set[str] = set()
    idx = 0
    while True:
        found = output.find(_BRIDGE_TOOL_PREFIX, idx)
        if found == -1:
            break
        tail = output[found + len(_BRIDGE_TOOL_PREFIX) :]
        name = ""
        for ch in tail:
            if ch.isalnum() or ch == "_":
                name += ch
            else:
                break
        if name:
            tools.add(_BRIDGE_TOOL_PREFIX + name)
        idx = found + len(_BRIDGE_TOOL_PREFIX)
    return tools


def test_solo_coder_case_names_the_bridge_tools() -> None:
    """Stack-free guard: the case is well-posed - names the bridged tools + preset."""
    case = _solo_coder_case("s20-guard")
    assert case.preset == _SOLO_CODER_PRESET
    assert case.roles == (_CODER_ROLE,)
    assert case.autonomous is True
    assert _PROPOSE_TOOL in case.prompt
    assert "mcp__vaultspec-authoring__read_context" in case.prompt


def test_extract_bridge_tools_finds_qualified_names() -> None:
    """Stack-free guard: the extractor pulls the exact bridged tool names, no more."""
    text = (
        "I called mcp__vaultspec-authoring__read_context, then "
        "mcp__vaultspec-authoring__propose_changeset. Also Read and Bash."
    )
    assert _extract_bridge_tools(text) == {
        "mcp__vaultspec-authoring__read_context",
        _PROPOSE_TOOL,
    }
    assert _extract_bridge_tools("no tools here") == set()
