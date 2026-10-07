"""Live proof of the tool-cores deterministic grounding floor (P01.S05).

The floor landed in P01.S01: an autonomous document-authoring role's ``session/new``
auto-permits the spawned CLI's native ``Read``/``Grep``/``Glob`` built-ins by exact
name. That wiring is proven deterministically against a real ACP subprocess in
``graph/tests/nodes/test_worker_native_read_tools.py``. THIS module proves the next
link live and mock-free: a real document agent, dispatched through the live loopback
stack, actually USES that permission to read a named ``.vault`` ADR mid-turn and cite
it - with ZERO ``.vault`` writes.

It is not a parallel driver. It reuses the shared acceptance harness
(``vaultspec_a2a.testing.acceptance``): ``reachable_stack`` for the infra gate, and
``AcceptanceHarness`` for token-mint + run-start against the live
``vaultspec-adr-research`` preset. What it adds is a NON-materializing observation:
rather than driving the review gates to apply (which writes documents), it consumes
the run's public v1 SSE progress stream (``GET /v1/runs/{run_id}/stream``) to witness
the mid-turn read and citation, then cancels the run before any gate applies. Zero
writes is enforced by a before/after snapshot of the engine workspace ``.vault``.

Observation surface - empirically validated, not guessed. A green Z.ai-lane run of this
exact harness (run id ``pw7-1784274009``, 2026-07-17, all-roles-Z.ai profile; the raw
frame capture that fixed the assumptions was ``pw7-1784273382``) showed the read does
NOT surface as a ``tool_call_start`` frame; it surfaces in the agent's
``message_chunk`` content, where the agent narrates the native discover-then-read
sequence (tried ``.vault``, found the file under ``.vault/adr/``, read it) and then
reproduces the ADR's own interior text. So the proof keys on message content:

* the target ADR filename appears in a document agent's ``message_chunk`` stream - the
  citation; and
* at least one DISTINCTIVE interior token of the ADR body (an identifier / version /
  path present in the file but NOT in the prompt - e.g. ``@agentclientprotocol/
  claude-agent-acp``, ``@anthropic-ai/claude-agent-sdk``, ``_KNOWN_MCP_SERVERS``)
  appears in that stream. A
  token the prompt never carried can only reach the output by the agent reading the
  file, so this is the load-bearing, hallucination-resistant read evidence; and
* zero created/modified/deleted files under the engine ``.vault`` across the run.

Infrastructure gate, not a masked failure (the sanctioned pw7 pattern): when no
loopback engine is discoverable, the engine vault carries no ADR to name, or the run's
provider is not ready (credential/usage gated), the test skips with a runbook pointer
naming the missing resource. When the stack IS present the assertions are fail-loud - a
run that never cites the ADR or never reproduces its interior FAILS, never passes.

Profile: this cost-bearing live proof is fixed to the committed ``fast`` profile.
That profile assigns every participating role to the low capability tier.  An
environment override is deliberately not accepted: changing a test's model tier must
be a reviewed source change, not an ambient shell setting.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack

import httpx
import pytest

from ..control.run_start_policy import required_role_ids
from ..streaming.sse_frames import iter_sse_events
from ..team.team_config import load_team_config
from ..testing import (
    GATEWAY_AUTH_HEADERS,
    OBSERVE_DEADLINE_SECONDS,
    PRESET_LIVE,
    AcceptanceCase,
    AcceptanceHarness,
    ResilientAuthoringClient,
    SseFrame,
    message_content,
    reachable_stack,
    resolve_selection,
    snapshot_vault,
    vault_write_delta,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..conftest import ExternalPrerequisiteRule


@dataclass(frozen=True, slots=True)
class _NamedAdrFloorContext:
    """Prepared live harness and evidence inputs for the named-ADR proof."""

    harness: AcceptanceHarness
    adr_name: str
    adr_stem: str
    tokens: list[str]


@dataclass(frozen=True, slots=True)
class _RagFloorContext:
    """Prepared live harness and workspace for the semantic proof."""

    harness: AcceptanceHarness
    workspace_root: Path


class _NamedAdrObservationOptions(TypedDict):
    """Evidence inputs for one named-ADR SSE observation."""

    adr_name: str
    adr_stem: str
    tokens: list[str]
    output_parts: list[str]


# Every real-provider service lane runs on the operator-configured served
# selection. It used to name the committed all-low "fast" model profile; a
# preset carries no model policy now, so the cost ceiling is the operator's
# choice of a low-cost entry from the current catalog (the same thing the
# provider-catalog live-selection prerequisite already asks for). The lane
# claims no particular provider - it certifies the bridge/tool floor, not who
# produced the text - but it MUST be a real one, which is what
# requires_live_selection pins.


def _pick_named_adr(vault_root: Path) -> Path | None:
    """Return an existing ADR in the engine vault to name in the prompt, or None.

    The proof must name a REAL ``.vault`` document the agent can actually read; the
    engine workspace vault - not this repo's - is the one the agent sees, so the
    target is selected from it at run time. Absent any ADR, the read-a-named-ADR
    proof is not expressible and the test skips honestly.
    """
    adr_dir = vault_root / "adr"
    if not adr_dir.is_dir():
        return None
    candidates = sorted(adr_dir.glob("*.md"))
    return candidates[0] if candidates else None


def _distinctive_tokens(adr_text: str, prompt: str, *, limit: int = 60) -> list[str]:
    """Interior tokens of the ADR body that the prompt never carried.

    Selects identifier/version/path-shaped tokens (>= 10 chars, carrying a digit or a
    structural ``_ / @ .`` character - so prose words are excluded) that do not appear
    in the prompt. An agent can only emit such a token by having read the file, so
    their presence in the output is the load-bearing read evidence.
    """
    tokens: dict[str, None] = {}
    for tok in re.findall(r"[A-Za-z0-9_./@:-]{10,}", adr_text):
        if not any(ch.isdigit() or ch in "_/@." for ch in tok):
            continue
        if tok in prompt:
            continue
        tokens[tok] = None
        if len(tokens) >= limit:
            break
    return list(tokens)


def _cites_named_adr(output: str, adr_name: str, adr_stem: str) -> bool:
    """True if *output* cites the target ADR by its filename OR its bare stem.

    A document agent naming the ADR by its ``.md`` filename or by its stem (the
    filename without the extension - e.g. ``2026-02-25-...-adr`` instead of
    ``2026-02-25-...-adr.md``) is the same citation; live agents (Claude in
    particular) paraphrase the extension away, so keying only on the ``.md``
    filename made this check phrasing-sensitive. Accepting the stem too keeps the
    citation robust across providers. Hallucination-resistance is UNAFFECTED: the
    stem is still the prompt-provided identifier, and the load-bearing proof that
    the file was actually read remains the separate distinctive-interior-token
    assertion, not this reference check.
    """
    return adr_name in output or adr_stem in output


async def _observe_named_adr_run(
    harness: AcceptanceHarness,
    gateway_client: httpx.AsyncClient,
    **options: Unpack[_NamedAdrObservationOptions],
) -> tuple[bool, list[str]]:
    """Observe the named-ADR evidence stream and cancel the run on exit."""
    deadline = time.monotonic() + OBSERVE_DEADLINE_SECONDS
    cited = False
    matched_tokens: list[str] = []
    try:
        async with gateway_client.stream(
            "GET",
            f"{harness.gateway_url}/v1/runs/{harness.run_id}/stream",
            timeout=httpx.Timeout(OBSERVE_DEADLINE_SECONDS, connect=10.0),
        ) as response:
            response.raise_for_status()
            async for event in iter_sse_events(response.aiter_lines()):
                payload = SseFrame.from_event(event).data
                content = message_content(payload)
                if content:
                    options["output_parts"].append(content)
                    joined = "".join(options["output_parts"])
                    if _cites_named_adr(
                        joined, options["adr_name"], options["adr_stem"]
                    ):
                        cited = True
                    matched_tokens = [
                        token for token in options["tokens"] if token in joined
                    ]
                if payload.get("type") == "thread_terminal":
                    break
                if (cited and matched_tokens) or time.monotonic() > deadline:
                    break
    finally:
        await gateway_client.post(
            f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
            timeout=30.0,
        )
    return cited, matched_tokens


async def _observe_rag_run(
    harness: AcceptanceHarness,
    gateway_client: httpx.AsyncClient,
    *,
    workspace_root: Path,
    output_parts: list[str],
) -> tuple[bool, bool, list[str]]:
    """Observe RAG evidence and cancel the run on exit."""
    deadline = time.monotonic() + OBSERVE_DEADLINE_SECONDS
    rag_invoked = False
    service_down = False
    resolving: list[str] = []
    try:
        async with gateway_client.stream(
            "GET",
            f"{harness.gateway_url}/v1/runs/{harness.run_id}/stream",
            timeout=httpx.Timeout(OBSERVE_DEADLINE_SECONDS, connect=10.0),
        ) as response:
            response.raise_for_status()
            async for event in iter_sse_events(response.aiter_lines()):
                payload = SseFrame.from_event(event).data
                content = message_content(payload)
                if content:
                    output_parts.append(content)
                    joined = "".join(output_parts)
                    if any(tool in joined for tool in _RAG_TOOLS):
                        rag_invoked = True
                    if _RAG_SERVICE_DOWN in joined.lower():
                        service_down = True
                    resolving = _resolving_citations(joined, workspace_root)
                if payload.get("type") == "thread_terminal":
                    break
                if (rag_invoked and resolving) or time.monotonic() > deadline:
                    break
    finally:
        await gateway_client.post(
            f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
            timeout=30.0,
        )
    return rag_invoked, service_down, resolving


def _floor_case(feature: str, adr_name: str) -> AcceptanceCase:
    """The live floor case: a research prompt that names the target ADR to ground on.

    Reuses the shared ``AcceptanceCase`` shape and the live preset. The prompt directs
    the agent to read the named ``.vault`` ADR and cite it, exercising exactly the
    native read floor. No ``gate_policy`` is set - this proof observes the mid-turn
    read and cancels before any gate, so it never materializes a document.
    """
    return AcceptanceCase(
        label="tool-cores-floor-live",
        preset=PRESET_LIVE,
        feature=feature,
        prompt=(
            "Ground this research in the existing decision record "
            f"'{adr_name}': read that .vault ADR in full and cite it by name in "
            "your findings before considering anything else. Summarize its "
            "problem statement and decision, quoting the ADR filename as the "
            "locator for each claim."
        ),
        roles=tuple(required_role_ids(load_team_config(PRESET_LIVE))),
        expected_doc_kinds=(),
        requires_live_selection=True,
    )


async def _prepare_named_adr_floor(
    vault_root: Path,
    gateway_url: str,
    engine_base_url: str,
    engine_bearer: str,
    external_prerequisite: ExternalPrerequisiteRule,
) -> _NamedAdrFloorContext:
    """Select the live ADR and prepare its read-evidence harness."""
    target_adr = _pick_named_adr(vault_root)
    if target_adr is None:
        external_prerequisite.absent(
            "engine-vault-adr",
            f"engine vault {vault_root / 'adr'} carries no ADR to name",
        )
    adr_name = target_adr.name
    adr_stem = target_adr.stem
    adr_text = target_adr.read_text(encoding="utf-8", errors="replace")
    feature = f"tool-cores-floor-{int(time.time())}"
    case = _floor_case(feature, adr_name)
    tokens = _distinctive_tokens(adr_text, case.prompt)
    if not tokens:
        external_prerequisite.absent(
            "engine-vault-adr",
            f"ADR {adr_name} carries no distinctive interior token absent from the "
            "prompt, so it cannot yield hallucination-resistant read evidence",
        )
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
    return _NamedAdrFloorContext(
        harness=harness,
        adr_name=adr_name,
        adr_stem=adr_stem,
        tokens=tokens,
    )


async def _run_named_adr_floor(
    context: _NamedAdrFloorContext,
) -> tuple[bool, list[str], dict[str, list[str]]]:
    """Observe one named-ADR run and return evidence plus its vault delta."""
    before = snapshot_vault(context.harness.vault_root)
    output_parts: list[str] = []

    async with ResilientAuthoringClient(
        context.harness.engine_base_url, context.harness.engine_bearer
    ) as ec:
        run_tokens = await context.harness.mint_role_tokens(
            ec, context.harness.run_id, context.harness.case.roles
        )
        async with httpx.AsyncClient(headers=GATEWAY_AUTH_HEADERS) as hc:
            await context.harness.run_start(
                hc,
                run_id=context.harness.run_id,
                tokens=run_tokens,
                feature=context.harness.case.feature,
                expect=201,
            )
            cited, matched_tokens = await _observe_named_adr_run(
                context.harness,
                hc,
                adr_name=context.adr_name,
                adr_stem=context.adr_stem,
                tokens=context.tokens,
                output_parts=output_parts,
            )

    after = snapshot_vault(context.harness.vault_root)
    return cited, matched_tokens, vault_write_delta(before, after)


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.asyncio
async def test_document_agent_reads_named_adr_midturn_and_cites(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Live: a document agent reads a named .vault ADR mid-turn and cites it.

    Zero .vault writes: the run is observed over its SSE stream and cancelled before
    any review gate applies; a before/after vault snapshot asserts no file changed.
    """
    stack = reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, engine_base_url, engine_bearer, vault_root = stack
    context = await _prepare_named_adr_floor(
        vault_root,
        gateway_url,
        engine_base_url,
        engine_bearer,
        external_prerequisite,
    )
    cited, matched_tokens, delta = await _run_named_adr_floor(context)

    assert cited, (
        f"no document agent cited {context.adr_name!r} (or its stem "
        f"{context.adr_stem!r}) in its "
        f"message stream within {OBSERVE_DEADLINE_SECONDS:.0f}s (run "
        f"{context.harness.run_id}); the floor was not exercised live"
    )
    assert matched_tokens, (
        f"the agent cited {context.adr_name!r} but reproduced none of its "
        f"distinctive interior tokens {context.tokens[:8]!r}...; a citation without "
        "interior content does "
        "not prove the file was actually read (run "
        f"{context.harness.run_id})"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the floor proof must not write to .vault, but the run changed it: {delta}"
    )


# --- Semantic tier (P03.S16 Claude / S17 Z.ai): agent invokes vaultspec-rag -------

# The rag MCP search tools the semantic tier surfaces (P03.S12 preset opt-in + S15
# persona). The prompt directs the document agent to invoke them so the proof observes
# a real mid-turn rag invocation, not a native read.
_RAG_TOOLS = (
    "mcp__vaultspec-rag__search_codebase",
    "mcp__vaultspec-rag__search_vault",
)
_RAG_SERVICE_DOWN = "service is not running"
_CITATION_RE = re.compile(r"([A-Za-z0-9_][\w./\\-]*\.(?:py|md|toml)):(\d+)")


def _rag_case(feature: str) -> AcceptanceCase:
    """The semantic case: a prompt that directs the agent to invoke the rag tools."""
    return AcceptanceCase(
        label="tool-cores-semantic-live",
        preset=PRESET_LIVE,
        feature=feature,
        prompt=(
            "Ground this research with the vaultspec-rag semantic search tools. "
            "Call mcp__vaultspec-rag__search_codebase for 'compose harness mcp "
            "servers allowlist' and mcp__vaultspec-rag__search_vault for 'tool-cores "
            "read-only grounding decision'. Report the top file:line locations each "
            "search returns and cite them verbatim before anything else."
        ),
        roles=tuple(required_role_ids(load_team_config(PRESET_LIVE))),
        expected_doc_kinds=(),
        requires_live_selection=True,
    )


def _resolving_citations(output: str, workspace_root: Path) -> list[str]:
    """Return output ``file:line`` citations whose path resolves under the workspace.

    A citation the agent could only produce from a real rag result pointing at a real
    indexed file - the load-bearing "citations resolve to real locations" evidence.
    Resolution is checked against the engine-scoped workspace the rag search was
    project-scoped to.
    """
    resolving: list[str] = []
    for match in _CITATION_RE.finditer(output):
        rel = match.group(1).replace("\\", "/")
        if (workspace_root / rel).is_file():
            resolving.append(match.group(0))
    return resolving


async def _prepare_rag_floor(
    gateway_url: str,
    engine_base_url: str,
    engine_bearer: str,
    vault_root: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> _RagFloorContext:
    """Prepare the live harness and workspace for the semantic proof."""
    workspace_root = vault_root.parent
    feature = f"tool-cores-semantic-{int(time.time())}"
    case = _rag_case(feature)
    selection, overrides = await resolve_selection(
        case, gateway_url, str(workspace_root), external_prerequisite
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
    return _RagFloorContext(harness=harness, workspace_root=workspace_root)


async def _run_rag_floor(
    context: _RagFloorContext,
) -> tuple[bool, bool, list[str], dict[str, list[str]]]:
    """Observe one semantic run and return evidence plus its vault delta."""
    before = snapshot_vault(context.harness.vault_root)
    output_parts: list[str] = []

    async with ResilientAuthoringClient(
        context.harness.engine_base_url, context.harness.engine_bearer
    ) as ec:
        run_tokens = await context.harness.mint_role_tokens(
            ec, context.harness.run_id, context.harness.case.roles
        )
        async with httpx.AsyncClient(headers=GATEWAY_AUTH_HEADERS) as hc:
            await context.harness.run_start(
                hc,
                run_id=context.harness.run_id,
                tokens=run_tokens,
                feature=context.harness.case.feature,
                expect=201,
            )
            rag_invoked, service_down, resolving = await _observe_rag_run(
                context.harness,
                hc,
                workspace_root=context.workspace_root,
                output_parts=output_parts,
            )

    after = snapshot_vault(context.harness.vault_root)
    return rag_invoked, service_down, resolving, vault_write_delta(before, after)


@pytest.mark.service
@pytest.mark.resource("loopback-stack")
@pytest.mark.asyncio
async def test_document_agent_invokes_rag_search_midturn_and_cites(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Live: a document agent invokes vaultspec-rag search mid-turn; citations resolve.

    The semantic-tier proof runs under the committed all-low ``fast`` profile.
    The agent invokes the surfaced ``mcp__vaultspec-rag__search_*`` tools, receives REAL
    results (never the "service not running" error), and its cited file:line locations
    resolve to real files in the engine-scoped, rag-indexed workspace. Zero document-dir
    writes: observed over the SSE stream and cancelled before any gate applies.

    Corroborating live evidence (recorded in the exec record, not asserted here - the
    daemon log is not a test surface): the rag service's access log shows the run's
    ``POST /search`` hitting :8766, a request native Read/Grep can never make.

    Pre-flight (see the S17 exec record): the :8766 service must be discoverable
    (``~/.vaultspec-rag/service.json`` present) and the engine-scoped workspace must be
    indexed on it, or the search returns no hits / the service-down error and the
    assertions fail loud.
    """
    stack = reachable_stack()
    if stack is None:
        external_prerequisite.absent("loopback-stack")
    gateway_url, engine_base_url, engine_bearer, vault_root = stack
    context = await _prepare_rag_floor(
        gateway_url,
        engine_base_url,
        engine_bearer,
        vault_root,
        external_prerequisite,
    )
    rag_invoked, service_down, resolving, delta = await _run_rag_floor(context)

    assert not service_down, (
        "the rag search returned the service-not-running error (run "
        f"{context.harness.run_id}); the :8766 service was "
        "undiscoverable/unreachable from the "
        "spawned agent env"
    )
    assert rag_invoked, (
        f"no document agent invoked a vaultspec-rag search tool {_RAG_TOOLS} in its "
        f"message stream within {OBSERVE_DEADLINE_SECONDS:.0f}s (run "
        f"{context.harness.run_id})"
    )
    assert resolving, (
        "the agent invoked rag search but cited no file:line that resolves under the "
        f"indexed workspace {context.workspace_root}; citations did not resolve to "
        f"real locations (run {context.harness.run_id})"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the semantic proof must not write to .vault, but the run changed it: {delta}"
    )


def test_rag_case_prompt_names_the_search_tools() -> None:
    """Stack-free guard: the semantic case names the rag tools and is well-posed."""
    case = _rag_case("tool-cores-semantic-guard")
    assert "mcp__vaultspec-rag__search_codebase" in case.prompt
    assert "mcp__vaultspec-rag__search_vault" in case.prompt
    assert case.preset == PRESET_LIVE
    assert case.gate_policy == {}
    assert case.expected_doc_kinds == ()


def test_resolving_citations_returns_only_real_paths(tmp_path: Path) -> None:
    """Stack-free guard: citation resolution accepts real paths, rejects fake ones.

    A resolution check that returned a hallucinated path would make the "citations
    resolve" assertion meaningless, so this pins that only on-disk paths count.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    output = "hits: src/mod.py:12, src/ghost.py:3, docs/missing.md:7"
    resolving = _resolving_citations(output, tmp_path)
    assert "src/mod.py:12" in resolving
    assert not any("ghost" in cite or "missing" in cite for cite in resolving)


def test_floor_case_names_the_target_adr_in_its_prompt() -> None:
    """Stack-free guard: the case prompt names the ADR and yields read evidence.

    A prompt that failed to name the target ADR, or an interior-token extractor that
    returned tokens already in the prompt, would make the read assertion untestable, so
    this pins the harness input and the evidence derivation - not a substitute for the
    live proof, a guard that the live proof is well-posed.
    """
    adr_name = "2026-07-17-tool-cores-adr.md"
    case = _floor_case("tool-cores-floor-guard", adr_name)
    assert adr_name in case.prompt
    assert case.preset == PRESET_LIVE
    assert case.gate_policy == {}
    assert case.expected_doc_kinds == ()

    sample_adr = (
        "# tool-cores adr\nThe pin @agentclientprotocol/claude-agent-acp@0.84.0 "
        "supersedes @zed-industries/claude-agent-acp@0.23.1; the registry "
        "_KNOWN_MCP_SERVERS is the single source; SDK 0.2.83 is behind.\n"
    )
    tokens = _distinctive_tokens(sample_adr, case.prompt)
    assert tokens, "distinctive interior tokens must be extractable from an ADR body"
    # Every extracted token is genuinely absent from the prompt (else echoing the
    # prompt would falsely pass the read assertion).
    assert all(tok not in case.prompt for tok in tokens)
    assert "_KNOWN_MCP_SERVERS" in tokens


def test_cites_named_adr_accepts_filename_and_stem() -> None:
    """Stack-free guard: the citation check accepts the .md filename OR the stem.

    Pins the reviewer-tracked hardening: a live agent that names the ADR by its stem
    (dropping the ``.md`` extension) cites it just as much as one that echoes the full
    filename. An unrelated document name must not register as a citation, so the check
    stays a genuine reference test - the hallucination-resistance still lives in the
    separate interior-token assertion, not here.
    """
    name = "2026-02-25-llm-context-provider-abstraction-adr.md"
    stem = "2026-02-25-llm-context-provider-abstraction-adr"
    # Full .md filename cited.
    assert _cites_named_adr(f"EVIDENCE: `{name}` (Problem Statement)", name, stem)
    # Bare stem cited (the paraphrase that broke the first Claude S05 run).
    assert _cites_named_adr(
        f"grounding in the llm-context-provider-abstraction ADR ({stem}) as decided",
        name,
        stem,
    )
    # An unrelated ADR name is NOT a citation of the target.
    assert not _cites_named_adr(
        "see 2026-07-17-tool-cores-adr.md for the grounding decision", name, stem
    )
