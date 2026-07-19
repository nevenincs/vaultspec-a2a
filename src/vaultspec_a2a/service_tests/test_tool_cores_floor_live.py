"""Live proof of the tool-cores deterministic grounding floor (P01.S05).

The floor landed in P01.S01: an autonomous document-authoring role's ``session/new``
auto-permits the spawned CLI's native ``Read``/``Grep``/``Glob`` built-ins by exact
name. That wiring is proven deterministically against a real ACP subprocess in
``graph/tests/nodes/test_worker_native_read_tools.py``. THIS module proves the next
link live and mock-free: a real document agent, dispatched through the live loopback
stack, actually USES that permission to read a named ``.vault`` ADR mid-turn and cite
it - with ZERO ``.vault`` writes.

It is not a parallel driver. It reuses the standing pw7 acceptance harness
(``test_pw7_acceptance``): ``_reachable_stack`` for the infra gate, and
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

Profile: the committed default is the Claude lane (S05's target), gated on the Claude
weekly usage window. The identical harness was validated on the Z.ai lane, which rides
the same ``AcpChatModel``/adapter (``factory.py``), by setting ``S05_PROFILE`` to an
all-Z.ai profile - the same run cited above. The Claude-lane evidence is a parameter
swap once Claude usage is unblocked.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ..api.schemas.enums import ServerEventType
from .test_pw7_acceptance import (
    _PRESET_LIVE,
    _RESEARCH_ADR_ROLES,
    AcceptanceCase,
    AcceptanceHarness,
    _reachable_stack,
)

if TYPE_CHECKING:
    from pathlib import Path

# The message frame types that carry an agent's mid-turn narration and output. The
# read/citation surface here (validated live), not in tool-call frames.
_MESSAGE_FRAMES = frozenset(
    {ServerEventType.MESSAGE_CHUNK.value, ServerEventType.THOUGHT_CHUNK.value}
)

# A live research turn takes minutes; bound the observation so a stalled run fails loud
# rather than hanging. The document agents read early, mid-Diverge/Synthesize.
_OBSERVE_DEADLINE_SECONDS = 900.0

# The model profile the run launches under. Default is the Claude lane (S05's target);
# override with S05_PROFILE=<all-Z.ai profile> to reproduce the Z.ai validation run.
_PROFILE_ID = os.environ.get("S05_PROFILE", "team-defaults")


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


# The vaultspec DOCUMENT surface - the directories an agent-authored document would
# materialize under. The engine's own runtime tree (``.vault/data``: its sqlite DBs,
# WAL files, graph cache, and the heartbeat ``service.json``) churns continuously and
# is NOT an agent write, so it is excluded from the write watcher - the floor proof's
# "zero .vault writes" means zero agent-origin DOCUMENT writes (validated live: a
# whole-tree watcher tripped only on ``.vault/data`` engine churn).
_DOCUMENT_DIRS = ("adr", "research", "audit", "plan", "exec", "reference", "index")


def _snapshot_vault(vault_root: Path) -> dict[str, tuple[float, int]]:
    """Map every agent-authorable document file to its (mtime, size).

    Scoped to the vaultspec document directories; the engine-owned ``.vault/data``
    runtime tree is excluded because its DB/WAL/heartbeat churn is not an agent write.
    """
    snapshot: dict[str, tuple[float, int]] = {}
    for doc_dir in _DOCUMENT_DIRS:
        base = vault_root / doc_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[str(path)] = (stat.st_mtime, stat.st_size)
    return snapshot


def _vault_write_delta(
    before: dict[str, tuple[float, int]], after: dict[str, tuple[float, int]]
) -> dict[str, list[str]]:
    """Return created/modified/deleted paths between two vault snapshots."""
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    return {"created": created, "modified": modified, "deleted": deleted}


def _message_content(payload: dict) -> str | None:
    """Return the content of a message/thought chunk frame, else None."""
    if payload.get("type") not in _MESSAGE_FRAMES:
        return None
    content = payload.get("content")
    return content if isinstance(content, str) else None


def _floor_case(feature: str, adr_name: str) -> AcceptanceCase:
    """The live floor case: a research prompt that names the target ADR to ground on.

    Reuses the pw7 ``AcceptanceCase`` shape and the live preset. The prompt directs the
    agent to read the named ``.vault`` ADR and cite it, exercising exactly the native
    read floor. No ``gate_policy`` is set - this proof observes the mid-turn read and
    cancels before any gate, so it never materializes a document.
    """
    return AcceptanceCase(
        label="tool-cores-floor-live",
        preset=_PRESET_LIVE,
        feature=feature,
        prompt=(
            "Ground this research in the existing decision record "
            f"'{adr_name}': read that .vault ADR in full and cite it by name in "
            "your findings before considering anything else. Summarize its "
            "problem statement and decision, quoting the ADR filename as the "
            "locator for each claim."
        ),
        roles=_RESEARCH_ADR_ROLES,
        expected_doc_kinds=(),
        profile_id=_PROFILE_ID,
    )


@pytest.mark.service
@pytest.mark.asyncio
async def test_document_agent_reads_named_adr_midturn_and_cites() -> None:
    """Live: a document agent reads a named .vault ADR mid-turn and cites it.

    Zero .vault writes: the run is observed over its SSE stream and cancelled before
    any review gate applies; a before/after vault snapshot asserts no file changed.
    """
    stack = _reachable_stack()
    if stack is None:
        pytest.skip(
            "no reachable loopback stack; boot a workspace-local `vaultspec serve "
            "--no-seat` engine plus the a2a gateway/worker with "
            "VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true (runbook), then set "
            "VAULTSPEC_ENGINE_SERVICE_JSON and select -m service"
        )
    engine_base_url, engine_bearer, vault_root = stack

    target_adr = _pick_named_adr(vault_root)
    if target_adr is None:
        pytest.skip(
            f"engine vault {vault_root / 'adr'} carries no ADR to name; the "
            "read-a-named-ADR floor proof needs at least one existing ADR to read"
        )
    adr_name = target_adr.name
    adr_stem = target_adr.stem
    adr_text = target_adr.read_text(encoding="utf-8", errors="replace")

    feature = f"tool-cores-floor-{int(time.time())}"
    case = _floor_case(feature, adr_name)
    tokens = _distinctive_tokens(adr_text, case.prompt)
    if not tokens:
        pytest.skip(
            f"ADR {adr_name} carries no distinctive interior token absent from the "
            "prompt; cannot form hallucination-resistant read evidence"
        )
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
    )

    before = _snapshot_vault(vault_root)
    output_parts: list[str] = []
    cited = False
    matched_tokens: list[str] = []

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
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
                            if _cites_named_adr(joined, adr_name, adr_stem):
                                cited = True
                            matched_tokens = [t for t in tokens if t in joined]
                        if payload.get("type") == "thread_terminal":
                            break
                        if (cited and matched_tokens) or time.monotonic() > deadline:
                            break
            finally:
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )

    after = _snapshot_vault(vault_root)
    delta = _vault_write_delta(before, after)

    assert cited, (
        f"no document agent cited {adr_name!r} (or its stem {adr_stem!r}) in its "
        f"message stream within {_OBSERVE_DEADLINE_SECONDS:.0f}s (run "
        f"{harness.run_id}); the floor was not exercised live"
    )
    assert matched_tokens, (
        f"the agent cited {adr_name!r} but reproduced none of its distinctive "
        f"interior tokens {tokens[:8]!r}...; a citation without interior content does "
        "not prove the file was actually read (run "
        f"{harness.run_id})"
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
        preset=_PRESET_LIVE,
        feature=feature,
        prompt=(
            "Ground this research with the vaultspec-rag semantic search tools. "
            "Call mcp__vaultspec-rag__search_codebase for 'compose harness mcp "
            "servers allowlist' and mcp__vaultspec-rag__search_vault for 'tool-cores "
            "read-only grounding decision'. Report the top file:line locations each "
            "search returns and cite them verbatim before anything else."
        ),
        roles=_RESEARCH_ADR_ROLES,
        expected_doc_kinds=(),
        profile_id=_PROFILE_ID,
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


@pytest.mark.service
@pytest.mark.asyncio
async def test_document_agent_invokes_rag_search_midturn_and_cites() -> None:
    """Live: a document agent invokes vaultspec-rag search mid-turn; citations resolve.

    The semantic-tier proof (P03.S16 Claude / S17 Z.ai, selected by ``S05_PROFILE``).
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
    stack = _reachable_stack()
    if stack is None:
        pytest.skip(
            "no reachable loopback stack; boot a workspace-local `vaultspec serve "
            "--no-seat` engine plus the a2a gateway/worker with "
            "VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true (runbook), then set "
            "VAULTSPEC_ENGINE_SERVICE_JSON and select -m service"
        )
    engine_base_url, engine_bearer, vault_root = stack
    workspace_root = vault_root.parent

    feature = f"tool-cores-semantic-{int(time.time())}"
    case = _rag_case(feature)
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
    )

    before = _snapshot_vault(vault_root)
    output_parts: list[str] = []
    rag_invoked = False
    service_down = False
    resolving: list[str] = []

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
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
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )

    after = _snapshot_vault(vault_root)
    delta = _vault_write_delta(before, after)

    assert not service_down, (
        "the rag search returned the service-not-running error (run "
        f"{harness.run_id}); the :8766 service was undiscoverable/unreachable from the "
        "spawned agent env"
    )
    assert rag_invoked, (
        f"no document agent invoked a vaultspec-rag search tool {_RAG_TOOLS} in its "
        f"message stream within {_OBSERVE_DEADLINE_SECONDS:.0f}s (run {harness.run_id})"
    )
    assert resolving, (
        "the agent invoked rag search but cited no file:line that resolves under the "
        f"indexed workspace {workspace_root}; citations did not resolve to real "
        f"locations (run {harness.run_id})"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the semantic proof must not write to .vault, but the run changed it: {delta}"
    )


def test_rag_case_prompt_names_the_search_tools() -> None:
    """Stack-free guard: the semantic case names the rag tools and is well-posed."""
    case = _rag_case("tool-cores-semantic-guard")
    assert "mcp__vaultspec-rag__search_codebase" in case.prompt
    assert "mcp__vaultspec-rag__search_vault" in case.prompt
    assert case.preset == _PRESET_LIVE
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
    assert case.preset == _PRESET_LIVE
    assert case.gate_policy == {}
    assert case.expected_doc_kinds == ()

    sample_adr = (
        "# tool-cores adr\nThe pin @agentclientprotocol/claude-agent-acp@0.59.0 "
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
