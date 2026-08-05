"""Live proof that the CODEX lane's authoring writes actually reach the engine.

The defect this closes was total and silent. ``codex app-server`` gates every MCP
tool call behind a server-initiated ``mcpServer/elicitation/request``; the client
answered it with a JSON-RPC method-not-found, codex resolved the approval as not
granted, and the model was handed the synthesized tool result ``user rejected MCP
tool call``. The turn then settled ``completed`` with real assistant prose, so a
document-authoring run reported success while producing nothing at all.

Nothing short of a real turn settles it, and nothing the MODEL says settles it
either. The load-bearing assertion here is an engine-side changeset scoped to
this run (``cs:<run_id>:*`` in ``GET /authoring/v1/proposals``): only a real
``propose_changeset`` that the bridge forwarded to the engine creates one, and
the agent cannot fabricate it. Narration is deliberately NOT proof - a prior
driver in this repository green-washed exactly that way, matching tool names that
were also present in its own prompt, which is the precise failure mode the
elicitation defect hid behind. Tool names seen in the narration are retained here
as a DIAGNOSTIC only, to help read a failure, and are never asserted on.

This is the Codex-lane counterpart of the claude-lane S20 bridge proof, and it
reuses that module's harness and its engine-side changeset reader rather than
restating them, so the two lanes are certified against one definition of proof.
The lane is pinned: the case declares ``codex``, and a configured live selection
naming any other provider SKIPS rather than running, because a pass recorded
against a lane this test makes no claim about would be worse than no coverage.

Re-arm (one command, with the served codex selection exported):

    uv run --no-sync --frozen pytest -m service \\
        src/vaultspec_a2a/service_tests/test_doc_editor_bridge_live.py

Service-marked, so deselected from the default suite. Absent prerequisites - no
loopback stack, no configured live selection - skip naming exactly what is
missing; when they are present every assertion is fail-loud.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import pytest

from .test_pw7_acceptance import (
    _GATEWAY_AUTH_HEADERS,
    _MODE_AUTONOMOUS,
    AcceptanceCase,
    AcceptanceHarness,
    _reachable_stack,
    _resolve_selection,
)
from .test_s20_solo_coder_bridge_live import (
    _ENGINE_POLL_SECONDS,
    _OBSERVE_DEADLINE_SECONDS,
    _extract_bridge_tools,
    _message_content,
    _parse_event,
    _run_changeset_ids,
)
from .test_tool_cores_floor_live import _snapshot_vault, _vault_write_delta

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule

_CODER_ROLE = "vaultspec-coder"
_SOLO_CODER_PRESET = "vaultspec-solo-coder"
_CODEX_PROVIDER = "codex"


def _codex_authoring_case(feature: str) -> AcceptanceCase:
    """A Codex-lane run that must author through the bridged propose tool."""
    return AcceptanceCase(
        label="codex-doc-editor-bridge",
        preset=_SOLO_CODER_PRESET,
        feature=feature,
        prompt=(
            "Author a short research note for this feature using ONLY your engine "
            "authoring tools. Your available MCP tools include "
            "mcp__vaultspec-authoring__read_context, "
            "mcp__vaultspec-authoring__propose_changeset, and "
            "mcp__vaultspec-authoring__request_approval. Call "
            "mcp__vaultspec-authoring__propose_changeset to create a whole-document "
            "research note titled 'Codex bridge proof'. Do NOT write files directly "
            "- author only through the engine authoring tools."
        ),
        roles=(_CODER_ROLE,),
        expected_doc_kinds=(),
        lane_provider=_CODEX_PROVIDER,
        requires_live_selection=True,
        autonomous=True,
    )


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.asyncio
async def test_codex_authoring_tool_call_reaches_the_engine(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Live: a Codex-lane run's bridged authoring call lands in the engine.

    Proven by ``cs:<run_id>:*`` appearing in ``GET /authoring/v1/proposals``.
    Before the Codex permission rung existed this could not happen at all: the
    approval codex raised for the tool went unanswered as a method-not-found, the
    call was resolved as rejected, and the run still completed - which is why a
    turn-completed status and real assistant prose are worth nothing here.

    A before/after document-dir snapshot also asserts zero ``.vault`` writes: the
    proposal belongs in the engine's review lane, never materialized to disk by
    the agent.
    """
    stack = _reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, engine_base_url, engine_bearer, vault_root = stack

    feature = f"codex-doc-editor-{int(time.time())}"
    case = _codex_authoring_case(feature)
    selection, overrides = await _resolve_selection(
        case, gateway_url, str(vault_root.parent)
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

    before = _snapshot_vault(vault_root)
    output_parts: list[str] = []
    run_changesets: set[str] = set()
    # Diagnostic only, NEVER asserted: a tool name the agent merely NARRATES
    # proves nothing, because the prompt above names those same tools.
    narrated_bridge_names: set[str] = set()

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
        run_tokens = {
            role: await harness._mint(ec, f"agent:{harness.run_id}:{role}", "agent")
            for role in case.roles
        }
        # Autonomous operation mode before run-start, so the engine's eligibility
        # layer auto-approves the mutating propose_changeset INTO the review lane
        # rather than parking it as awaiting_permission. The human apply-gate
        # still lives downstream; this is the declared run mode reaching the
        # engine, not a bypass. A distinct human principal sets it, clearing the
        # self-approval ban.
        mode_setter = await harness._mint(ec, f"mode-setter:{harness.run_id}", "human")
        await harness._set_mode(ec, _MODE_AUTONOMOUS, setter_token=mode_setter)
        # The gateway seam is authenticated; the harness takes the client from its
        # caller, so the bearer belongs HERE. Built unauthenticated, every gateway
        # call answers a truthful 401 and the run never starts.
        async with httpx.AsyncClient(headers=_GATEWAY_AUTH_HEADERS) as hc:
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
                            content = _message_content(payload)
                            if content:
                                output_parts.append(content)
                                narrated_bridge_names.update(
                                    _extract_bridge_tools("".join(output_parts))
                                )
                            terminal = payload.get("type") == "thread_terminal"
                        now = time.monotonic()
                        # Poll the ENGINE, never the narration.
                        if now - last_engine_poll >= _ENGINE_POLL_SECONDS:
                            last_engine_poll = now
                            run_changesets = await _run_changeset_ids(
                                ec, harness.run_id
                            )
                        if run_changesets or now > deadline:
                            break
                        if terminal:
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
        "the Codex-lane run created no engine changeset scoped to run "
        f"{harness.run_id} within {_OBSERVE_DEADLINE_SECONDS:.0f}s "
        f"(cs:{harness.run_id}:* absent from /authoring/v1/proposals). The "
        "authoring call never reached the engine - which is exactly what the "
        "unanswered codex tool-approval produced, a run that completes and "
        "writes nothing. Narrated bridge names seen (diagnostic, NOT proof): "
        f"{sorted(narrated_bridge_names)}"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"this proof must not write to .vault, but the run changed it: {delta}"
    )
