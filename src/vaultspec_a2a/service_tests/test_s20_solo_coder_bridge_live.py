"""Live S20 proof: a solo-coder invokes the bridged authoring tools mid-turn.

The a2a-edge-conformance S20 leg (which closes S18+S20 together): the production
binding-construction site (task #40) arms the ``vaultspec-solo-coder`` preset's
authoring bridge, and the cold-start fix (7.58s -> 1.27s) lets the bridge's tools
reach the model in time. This drives the real preset through the live loopback
stack and witnesses the coder NATIVELY invoke an ``mcp__vaultspec-authoring__*``
tool mid-turn - the agent-initiated authoring path the whole bridge exists for.

Route (see the S20 exec record): the run-start bundle is minted per-agent_id and
supplied at the GATEWAY seam (the pw7 pattern), keyed by ``vaultspec-coder``, so
it satisfies the run_start coverage gate without depending on the engine's
role-key minting (the dashboard role-key fix is unmerged at authoring time).

Proof surface - UNFORGEABLE engine-side corroboration, not narration:

The load-bearing assertion is that a changeset scoped to THIS run
(``cs:<run_id>:*``) lands in the engine's authoring plane
(``GET /authoring/v1/proposals``). Only a real ``propose_changeset`` tool call
that the bridge forwards to the engine creates such a changeset - the agent cannot
fabricate one by talking about it. Paired with the zero-``.vault``-writes snapshot
(the proposal lands in the review lane, never materialized to disk here), this pins
the native surfacing->invocation->engine-effect path end to end.

Why the earlier revision of this driver false-greened (both now guarded): it
detected "invocation" by substring-matching ``mcp__vaultspec-authoring__`` in the
agent's ``message_chunk`` narration, but those exact tool names are ALSO in this
driver's own prompt - so a prompt-echo (the agent merely NAMING the tools, or
reporting they were unavailable) tripped the match without any real call. And its
zero-writes check only held because it CANCELLED the run at the first narration
match (~13s), before a fallback direct write could complete. This revision asserts
only the engine changeset and does NOT cancel before verification; the narration
scan is retained solely as a diagnostic (never asserted).

Infrastructure gate, not a masked failure: when no loopback stack is reachable,
or the run's provider is credential/usage gated, the test skips with a runbook
pointer. When the stack IS present the assertion is fail-loud - and it stays red
until the bridge tools actually surface to the coder at runtime (the S18/S20
surfacing work), which is the honest state of the proof.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ..api.schemas.enums import ServerEventType
from .test_pw7_acceptance import (
    _MODE_AUTONOMOUS,
    AcceptanceCase,
    AcceptanceHarness,
    _dig,
    _items,
    _reachable_stack,
)
from .test_tool_cores_floor_live import (
    _message_content,
    _snapshot_vault,
    _vault_write_delta,
)

if TYPE_CHECKING:
    from ..authoring import AuthoringClient

_MESSAGE_FRAMES = frozenset(
    {ServerEventType.MESSAGE_CHUNK.value, ServerEventType.THOUGHT_CHUNK.value}
)
_OBSERVE_DEADLINE_SECONDS = 900.0
# Cadence for polling the engine authoring plane for this run's changeset.
_ENGINE_POLL_SECONDS = 4.0
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


async def _run_changeset_ids(ec: AuthoringClient, run_id: str) -> set[str]:
    """Return this run's changeset ids present in the engine authoring plane.

    A changeset id embeds the run id (``cs:<run_id>:<phase>-r<cycle>``), so a match
    is unforgeable proof the bridge forwarded a real ``propose_changeset`` to the
    engine. Scans every lane ``GET /authoring/v1/proposals`` exposes (the default
    ``items`` plus the ``applied_under_policy`` projection) so a proposal is found
    whatever verdict state it has reached.
    """
    resp = await ec.get("/v1/proposals", with_actor=False)
    data = resp.data if isinstance(resp.data, dict) else {}
    found: set[str] = set()
    lanes: list[object] = [data]
    applied = data.get("applied_under_policy")
    if isinstance(applied, dict):
        lanes.append(applied)
    for lane in lanes:
        for item in _items(lane):
            changeset = _dig(item, "changeset_id") or ""
            if run_id in changeset:
                found.add(changeset)
    return found


@pytest.mark.service
@pytest.mark.asyncio
async def test_solo_coder_invokes_bridged_authoring_tool_midturn() -> None:
    """Live: a solo-coder natively invokes a bridged authoring tool mid-turn.

    Proven by an engine-side changeset scoped to this run
    (``cs:<run_id>:*`` in ``GET /authoring/v1/proposals``) - only a real
    ``propose_changeset`` the bridge forwards creates one. The run is observed over
    its SSE stream WITHOUT an early cancel; the engine is polled for the changeset
    until it appears, the run terminates, or the deadline elapses. A before/after
    document-dir snapshot asserts zero ``.vault`` writes: the proposal lands in the
    engine review lane, never materialized to disk here.
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
    run_changesets: set[str] = set()
    # Diagnostic only (NEVER asserted): the bridge tool names that appear in the
    # agent's narration. Retained to surface prompt-echo vs. real invocation when
    # reading a failure, but proof rests solely on the engine changeset below.
    narrated_bridge_names: set[str] = set()

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
        # Per-agent_id token minted here and supplied at the gateway seam (pw7
        # pattern): keyed by the coder's agent_id so the run_start coverage gate
        # passes without the engine's role-key minting.
        run_tokens = {
            role: await harness._mint(ec, f"agent:{harness.run_id}:{role}", "agent")
            for role in case.roles
        }
        # Operation-mode = autonomous BEFORE run-start, so the engine's authoring
        # eligibility layer AUTO-APPROVES the mutating propose_changeset INTO the
        # review lane instead of gating it as ``awaiting_permission``. This is the
        # declared run mode reaching the engine's approval layer, NOT a bypass:
        # autonomous runs auto-approve mutating ops into the review lane, where the
        # human apply-gate still lives. Replicates the pw7 acceptance AUTO lane's
        # device verbatim (``AcceptanceHarness._set_mode`` -> POST /v1/mode
        # ``set_operation_mode``; see the AUTO gate mechanics in
        # ``test_pw7_acceptance``). A distinct human principal is the mode-policy
        # setter (mode-set requires a human/system actor, clearing the
        # self-approval ban). The mode must be live before the run submits the
        # gated op.
        mode_setter = await harness._mint(ec, f"mode-setter:{harness.run_id}", "human")
        await harness._set_mode(ec, _MODE_AUTONOMOUS, setter_token=mode_setter)
        async with httpx.AsyncClient() as hc:
            await harness._run_start(
                hc,
                run_id=harness.run_id,
                tokens=run_tokens,
                feature=feature,
                expect=201,
            )
            deadline = time.monotonic() + _OBSERVE_DEADLINE_SECONDS
            last_engine_poll = 0.0
            try:
                async with hc.stream(
                    "GET",
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/stream",
                    timeout=httpx.Timeout(_OBSERVE_DEADLINE_SECONDS, connect=10.0),
                ) as response:
                    response.raise_for_status()
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        terminal = False
                        if line.startswith("data:"):
                            payload = _parse_event(line[len("data:") :].strip())
                            if payload is not None:
                                content = _message_content(payload)
                                if content:
                                    output_parts.append(content)
                                    narrated_bridge_names.update(
                                        _extract_bridge_tools("".join(output_parts))
                                    )
                                terminal = payload.get("type") == "thread_terminal"
                        now = time.monotonic()
                        # Poll the engine (not the narration) for this run's
                        # changeset - the unforgeable proof of a real invocation.
                        if now - last_engine_poll >= _ENGINE_POLL_SECONDS:
                            last_engine_poll = now
                            run_changesets = await _run_changeset_ids(
                                ec, harness.run_id
                            )
                        if run_changesets or now > deadline:
                            break
                        if terminal:
                            # Final authoritative check after the run settles.
                            run_changesets = await _run_changeset_ids(
                                ec, harness.run_id
                            )
                            break
            finally:
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )

    after = _snapshot_vault(vault_root)
    delta = _vault_write_delta(before, after)

    assert run_changesets, (
        "the solo-coder did not create any engine changeset scoped to run "
        f"{harness.run_id} within {_OBSERVE_DEADLINE_SECONDS:.0f}s "
        f"(cs:{harness.run_id}:* absent from /authoring/v1/proposals); the bridged "
        "authoring path was not exercised live. Narrated bridge names seen "
        f"(diagnostic, not proof): {sorted(narrated_bridge_names)}"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the S20 proof must not write to .vault, but the run changed it: {delta}"
    )


def _parse_event(body: str) -> dict | None:
    """Parse one SSE ``data:`` payload into a dict, or None if not a JSON object."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


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
