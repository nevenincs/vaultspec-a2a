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

import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ..testing import (
    CODER_ROLE,
    MODE_AUTONOMOUS,
    OBSERVE_DEADLINE_SECONDS,
    SOLO_CODER_PRESET,
    AcceptanceCase,
    AcceptanceHarness,
    ResilientAuthoringClient,
    observe_bridged_authoring_run,
    reachable_stack,
    resolve_selection,
    snapshot_vault,
    vault_write_delta,
)
from ..testing.acceptance import _extract_bridge_tools

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule

# Every real-provider service lane runs on the operator-configured served
# selection. It used to name the committed all-low "fast" model profile; a
# preset carries no model policy now, so the cost ceiling is the operator's
# choice of a low-cost entry from the current catalog (the same thing the
# provider-catalog live-selection prerequisite already asks for). The lane
# claims no particular provider - it certifies the bridge/tool floor, not who
# produced the text - but it MUST be a real one, which is what
# requires_live_selection pins.

# The bridged authoring tool the solo-coder should reach. Invoking it mid-turn
# proves the surfacing->invocation path end to end.
_PROPOSE_TOOL = "mcp__vaultspec-authoring__propose_changeset"


def _solo_coder_case(feature: str) -> AcceptanceCase:
    """A solo-coder run that must author via the bridged propose tool."""
    return AcceptanceCase(
        label="s20-solo-coder-bridge",
        preset=SOLO_CODER_PRESET,
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
        roles=(CODER_ROLE,),
        expected_doc_kinds=(),
        requires_live_selection=True,
        autonomous=True,
    )


async def _run_solo_coder_proof(
    case: AcceptanceCase,
    harness: AcceptanceHarness,
    feature: str,
) -> tuple[set[str], dict[str, list[str]], set[str]]:
    before = snapshot_vault(harness.vault_root)
    output_parts: list[str] = []
    # Diagnostic only (NEVER asserted): the bridge tool names that appear in the
    # agent's narration. Retained to surface prompt-echo vs. real invocation when
    # reading a failure, but proof rests solely on the engine changeset below.
    narrated_bridge_names: set[str] = set()

    async with ResilientAuthoringClient(
        harness.engine_base_url, harness.engine_bearer
    ) as ec:
        # Per-agent_id token minted here and supplied at the gateway seam (pw7
        # pattern): keyed by the coder's agent_id so the run_start coverage gate
        # passes without the engine's role-key minting.
        run_tokens = {
            role: await harness.mint(ec, f"agent:{harness.run_id}:{role}", "agent")
            for role in case.roles
        }
        # Operation-mode = autonomous BEFORE run-start, so the engine's authoring
        # eligibility layer AUTO-APPROVES the mutating propose_changeset INTO the
        # review lane instead of gating it as ``awaiting_permission``. This is the
        # declared run mode reaching the engine's approval layer, NOT a bypass:
        # autonomous runs auto-approve mutating ops into the review lane, where the
        # human apply-gate still lives. Replicates the acceptance AUTO lane's
        # device verbatim (``AcceptanceHarness.set_mode`` -> POST /v1/mode
        # ``set_operation_mode``; see the AUTO gate mechanics in
        # ``vaultspec_a2a.testing.acceptance``). A distinct human principal is the
        # mode-policy setter (mode-set requires a human/system actor, clearing the
        # self-approval ban). The mode must be live before the run submits the
        # gated op.
        mode_setter = await harness.mint(ec, f"mode-setter:{harness.run_id}", "human")
        await harness.set_mode(ec, MODE_AUTONOMOUS, setter_token=mode_setter)
        async with httpx.AsyncClient() as hc:
            await harness.run_start(
                hc,
                run_id=harness.run_id,
                tokens=run_tokens,
                feature=feature,
                expect=201,
            )
            run_changesets = await observe_bridged_authoring_run(
                ec,
                harness,
                hc,
                output_parts,
                narrated_bridge_names,
            )

    after = snapshot_vault(harness.vault_root)
    delta = vault_write_delta(before, after)
    return run_changesets, delta, narrated_bridge_names


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.asyncio
async def test_solo_coder_invokes_bridged_authoring_tool_midturn(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Live: a solo-coder natively invokes a bridged authoring tool mid-turn.

    Proven by an engine-side changeset scoped to this run
    (``cs:<run_id>:*`` in ``GET /authoring/v1/proposals``) - only a real
    ``propose_changeset`` the bridge forwards creates one. The run is observed over
    its SSE stream WITHOUT an early cancel; the engine is polled for the changeset
    until it appears, the run terminates, or the deadline elapses. A before/after
    document-dir snapshot asserts zero ``.vault`` writes: the proposal lands in the
    engine review lane, never materialized to disk here.
    """
    stack = reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, engine_base_url, engine_bearer, vault_root = stack

    feature = f"s20-solo-coder-{int(time.time())}"
    case = _solo_coder_case(feature)
    selection, overrides = await resolve_selection(
        case, gateway_url, str(vault_root.parent), external_prerequisite
    )
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
        gateway_url=gateway_url,
        selection=selection,
        overrides=overrides,
    )

    run_changesets, delta, narrated_bridge_names = await _run_solo_coder_proof(
        case, harness, feature
    )

    assert run_changesets, (
        "the solo-coder did not create any engine changeset scoped to run "
        f"{harness.run_id} within {OBSERVE_DEADLINE_SECONDS:.0f}s "
        f"(cs:{harness.run_id}:* absent from /authoring/v1/proposals); the bridged "
        "authoring path was not exercised live. Narrated bridge names seen "
        f"(diagnostic, not proof): {sorted(narrated_bridge_names)}"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the S20 proof must not write to .vault, but the run changed it: {delta}"
    )


def test_solo_coder_case_names_the_bridge_tools() -> None:
    """Stack-free guard: the case is well-posed - names the bridged tools + preset."""
    case = _solo_coder_case("s20-guard")
    assert case.preset == SOLO_CODER_PRESET
    assert case.roles == (CODER_ROLE,)
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
