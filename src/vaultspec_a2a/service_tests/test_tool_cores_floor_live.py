"""Live Claude-lane proof of the tool-cores deterministic grounding floor (P01.S05).

The floor landed in P01.S01: an autonomous document-authoring role's ``session/new``
auto-permits the spawned CLI's native ``Read``/``Grep``/``Glob`` built-ins by exact
name. That wiring is proven deterministically against a real ACP subprocess in
``graph/tests/nodes/test_worker_native_read_tools.py``. THIS module proves the next
link live and mock-free: a real Claude document agent, dispatched through the live
loopback stack, actually USES that permission to read a named ``.vault`` ADR mid-turn
and cite it - with ZERO ``.vault`` writes.

It is not a parallel driver. It reuses the standing pw7 acceptance harness
(``test_pw7_acceptance``): ``_reachable_stack`` for the infra gate, and
``AcceptanceHarness`` for token-mint + run-start against the live
``vaultspec-adr-research`` preset. What it adds is a NON-materializing observation:
rather than driving the review gates to apply (which writes documents), it consumes
the run's public v1 SSE progress stream (``GET /v1/runs/{run_id}/stream``) to witness
the mid-turn read and citation, then cancels the run before any gate applies. Zero
writes is enforced by a before/after snapshot of the engine workspace ``.vault``.

Evidence asserted, bound to the real event schema (``ServerEventType``, ``ToolKind``,
``ToolCallStartEvent``/``MessageChunkEvent``), so a schema drift breaks at import
rather than passing silently:

* a ``tool_call_start`` (or ``tool_call_update``) frame of kind ``read`` whose
  ``locations[].path`` (or ``title``) names the target ADR file - the mid-turn read;
* a ``message_chunk`` frame whose accumulated content cites that ADR by stem - the
  citation;
* zero created/modified/deleted files under the engine ``.vault`` across the run.

Infrastructure gate, not a masked failure (the sanctioned pw7 pattern): when no
loopback engine is discoverable (``resolve_engine`` is None / ``_reachable_stack`` is
None), or the engine vault carries no ADR to name, or the Claude provider is not ready
(credential-gated), the test skips with a runbook pointer naming the missing resource.
When the stack IS present the assertions are fail-loud - a run that never emits the
read or the citation FAILS, it is never reported as passing.

Honest limit (unproven until first live run): whether the research_adr researcher
emits the native read as a surfaced ``tool_call_start`` frame on the run stream, and
whether its kind/title distinguishes the native ``Read`` built-in from the engine
catalog's ``read_context``, is confirmed on the first green live run; the assertion
targets the read of the named ADR path (the load-bearing evidence) and records the
native-vs-catalog refinement as a follow-up. This module is committed runnable ahead
of that run because the live engine is not discoverable in the authoring session and
Claude usage is limit-gated; it arms the proof to fire the moment infra + usage are up.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ..api.schemas.enums import ServerEventType, ToolKind
from .test_pw7_acceptance import (
    _PRESET_LIVE,
    _RESEARCH_ADR_ROLES,
    AcceptanceCase,
    AcceptanceHarness,
    _reachable_stack,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# The read-tool-call and message frame types the run SSE relay emits (real schema).
_READ_TOOL_FRAMES = frozenset(
    {ServerEventType.TOOL_CALL_START, ServerEventType.TOOL_CALL_UPDATE}
)
_READ_KIND = ToolKind.READ.value

# A live Claude research turn takes minutes; bound the observation so a stalled run
# fails loud rather than hanging. The researcher reads mid-Diverge, early in the run.
_OBSERVE_DEADLINE_SECONDS = 600.0


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


def _snapshot_vault(vault_root: Path) -> dict[str, tuple[float, int]]:
    """Map every file under *vault_root* to its (mtime, size) - the write watcher."""
    snapshot: dict[str, tuple[float, int]] = {}
    for path in vault_root.rglob("*"):
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


def _iter_sse_payloads(lines: Iterable[str]) -> Iterable[dict]:
    """Yield the JSON payload of each SSE ``data:`` frame in a line stream."""
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        body = stripped[len("data:") :].strip()
        if not body:
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def _frame_reads_path(payload: dict, target_name: str) -> bool:
    """True if *payload* is a read tool-call frame naming *target_name*.

    Matches a ``tool_call_start``/``tool_call_update`` of kind ``read`` whose
    ``locations[].path`` or ``title`` contains the target ADR filename - the
    mid-turn read of the named document.
    """
    if payload.get("type") not in {t.value for t in _READ_TOOL_FRAMES}:
        return False
    if payload.get("kind") not in (_READ_KIND, None):
        return False
    locations = payload.get("locations") or []
    if any(target_name in (loc.get("path") or "") for loc in locations):
        return True
    title = payload.get("title") or ""
    return target_name in title


def _frame_cites(payload: dict, target_stem: str) -> bool:
    """True if *payload* is a message-chunk citing the target ADR by stem."""
    if payload.get("type") != ServerEventType.MESSAGE_CHUNK.value:
        return False
    return target_stem in (payload.get("content") or "")


def _floor_case(feature: str, adr_name: str) -> AcceptanceCase:
    """The live floor case: a research prompt that names the target ADR to ground on.

    Reuses the pw7 ``AcceptanceCase`` shape and the live Claude preset. The prompt
    directs the researcher to read the named ``.vault`` ADR and cite it, exercising
    exactly the native read floor. No ``gate_policy`` is set - this proof observes the
    mid-turn read and cancels before any gate, so it never materializes a document.
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
    )


@pytest.mark.service
@pytest.mark.asyncio
async def test_claude_document_agent_reads_named_adr_midturn_and_cites() -> None:
    """Live: a Claude document agent reads a named .vault ADR mid-turn and cites it.

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

    feature = f"tool-cores-floor-{int(time.time())}"
    case = _floor_case(feature, adr_name)
    harness = AcceptanceHarness(
        case=case,
        engine_base_url=engine_base_url,
        engine_bearer=engine_bearer,
        vault_root=vault_root,
    )

    before = _snapshot_vault(vault_root)
    saw_read = False
    saw_citation = False

    from .test_pw7_acceptance import _ResilientAuthoringClient

    async with _ResilientAuthoringClient(engine_base_url, engine_bearer) as ec:
        tokens = {
            role: await harness._mint(ec, f"agent:{harness.run_id}:{role}", "agent")
            for role in case.roles
        }
        async with httpx.AsyncClient() as hc:
            await harness._run_start(
                hc,
                run_id=harness.run_id,
                tokens=tokens,
                feature=feature,
                expect=201,
            )
            # Confirm the Claude provider is actually ready before asserting a live
            # read; an unready provider is a truthful credential/usage skip, not a
            # code failure.
            status = await harness._run_status(hc)
            assignments = status.get("assignments") or []
            claude_ready = any(
                a.get("provider_id") == "claude" and a.get("provider_ready")
                for a in assignments
            )
            if assignments and not claude_ready:
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )
                pytest.skip(
                    "Claude provider not ready for this run (credential/usage gated); "
                    "this is a truthful skip - the floor wiring is proven in "
                    "test_worker_native_read_tools, the live read awaits Claude access"
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
                        for payload in _iter_sse_payloads([raw_line]):
                            if _frame_reads_path(payload, adr_name):
                                saw_read = True
                            if _frame_cites(payload, adr_stem):
                                saw_citation = True
                            if payload.get("type") == "thread_terminal":
                                break
                        if (saw_read and saw_citation) or time.monotonic() > deadline:
                            break
            finally:
                # Cancel before any gate applies - the zero-writes guarantee does not
                # rely on the run ending on its own.
                await hc.post(
                    f"{harness.gateway_url}/v1/runs/{harness.run_id}/cancel",
                    timeout=30.0,
                )

    after = _snapshot_vault(vault_root)
    delta = _vault_write_delta(before, after)

    assert saw_read, (
        f"no mid-turn read of {adr_name!r} observed on the run SSE stream within "
        f"{_OBSERVE_DEADLINE_SECONDS:.0f}s; the document agent did not read the "
        "named ADR (floor not exercised live)"
    )
    assert saw_citation, (
        f"the agent never cited {adr_stem!r} in a message chunk; a read without a "
        "citation does not prove grounding reached the output"
    )
    assert delta == {"created": [], "modified": [], "deleted": []}, (
        f"the floor proof must not write to .vault, but the run changed it: {delta}"
    )


def test_floor_case_names_the_target_adr_in_its_prompt() -> None:
    """Stack-free guard: the case prompt actually names the ADR it will assert on.

    A prompt that failed to name the target ADR would make the read/citation
    assertion untestable (the agent could not know which document to read), so this
    pins the harness input itself - not a substitute for the live proof, a guard that
    the live proof is well-posed.
    """
    case = _floor_case("tool-cores-floor-guard", "2026-07-17-tool-cores-adr.md")
    assert "2026-07-17-tool-cores-adr.md" in case.prompt
    assert case.preset == _PRESET_LIVE
    # No gate policy: the proof observes and cancels, never materializes.
    assert case.gate_policy == {}
    assert case.expected_doc_kinds == ()
