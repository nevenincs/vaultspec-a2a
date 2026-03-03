---
adr_id: 026
title: pipeline_phase Population
date: 2026-03-03
status: Implemented
related:
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/020-blackboard-content-mounting.md
  - docs/adrs/021-persistent-task-queue-schema.md
  - docs/adrs/022-contextual-anchoring-graph-lifecycle.md
---

# ADR-026: pipeline_phase Population

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

ADR-019 added `pipeline_phase: str | None` to `TeamState` with the note "None until
the supervisor sets it on the first routing pass." The field was never actually
populated at runtime. This gap is recorded as DRIFT-11 in the vaultspec rule drift
audit (`docs/audits/2026-03-03-vaultspec-rule-drift.md`):

> **DRIFT-11 (MEDIUM):** `pipeline_phase` never set at runtime. Supervisor returns
> `{"next": route}` only. Three downstream consumers operate with `pipeline_phase =
None` on every invocation.

The three downstream consumers blocked by this gap are:

| Consumer                                          | Dependency on pipeline_phase                                                                                                                                                           |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ADR-022 anchoring (`build_anchoring_context`)     | Includes phase in the anchoring summary injected at position [2]. With `None`, the phase line is omitted — supervisor and workers have no phase signal.                                |
| ADR-020 mounting (`_select_paths`)                | Selects phase-scoped documents for injection at position [3]. With `None`, `vault_index.get(None)` returns nothing — only ADR documents are ever mounted, regardless of session stage. |
| ADR-021 queue injection (`_filter_queue_content`) | Activated only when `pipeline_phase in {"plan", "exec"}`. With `None`, queue content is never injected — workers cannot see their task queue.                                          |

Without `pipeline_phase` being set, the entire SDD pipeline awareness stack
(ADR-019 through ADR-022) operates at reduced fidelity on every invocation.

### 1.1 Why Phase Cannot Be Set Once at Graph Compilation

`pipeline_phase` must reflect the current state of the feature's artifact inventory.
A session may begin with no exec artifacts (`phase = plan`) and end with several
(`phase = exec`). Setting phase once at graph compilation produces a stale value
for the remainder of the session. Phase must be recomputed on every supervisor
invocation from the current `vault_index`.

### 1.2 Why Phase Should Not Be LLM-Driven

`pipeline_phase` is consumed by anchoring (ADR-022), document mounting (ADR-020),
and queue injection (ADR-021). A hallucinated phase value cascades into wrong
documents being injected and the wrong queue being shown to workers. All surveyed
multi-agent frameworks (MetaGPT, CrewAI) use deterministic phase management; none
delegate phase determination to LLM output. The blackboard control-unit pattern
(arXiv 2507.01701) explicitly designates phase tracking as a control-unit
responsibility — it observes blackboard state, it does not produce it.

## 2. Decision

### 2.1 `infer_phase_from_vault_index()` Function

A new module `lib/core/phase.py` provides the canonical phase inference function:

```python
# lib/core/phase.py
from __future__ import annotations

__all__ = ["PHASE_ORDER", "infer_phase_from_vault_index"]

PHASE_ORDER: list[str] = ["research", "reference", "adr", "plan", "exec", "audit"]

_PHASE_ORDER = PHASE_ORDER  # module-internal alias


def infer_phase_from_vault_index(vault_index: dict[str, list[str]]) -> str:
    """Return the highest phase that has at least one entry in vault_index.

    Iterates phases in reverse order (audit → research). The first phase
    found with a non-empty list is the inferred current phase.

    Returns "research" when vault_index is empty or no phase has entries —
    this is the correct default for a first session with no artifacts yet.

    Args:
        vault_index: Mapping of phase name to list of .vault/-relative paths,
                     as stored in TeamState["vault_index"] (ADR-019 §2.1).

    Returns:
        A phase name from PHASE_ORDER.
    """
    for phase in reversed(_PHASE_ORDER):
        if vault_index.get(phase):
            return phase
    return "research"
```

**Module contract:**

- `PHASE_ORDER` is the authoritative ordered list of the six pipeline phases. It
  is exported for use by any consumer that needs to compare or index phases
  (e.g., Option C tiebreaker logic, if added in a future ADR).
- `infer_phase_from_vault_index` is a pure function — no I/O, no side effects.
  It is independently testable without any LangGraph context.
- `lib/core/phase.py` must declare `__all__ = ["PHASE_ORDER", "infer_phase_from_vault_index"]`.
  No other names are exported.

### 2.2 Supervisor Integration

`create_supervisor_node()` (`lib/core/nodes/supervisor.py`) is amended to call
`infer_phase_from_vault_index` on every invocation, before building the anchoring
context, and to include `pipeline_phase` in its return dict:

```python
from ..phase import infer_phase_from_vault_index

async def supervisor_node(state: TeamState) -> dict[str, Any]:
    # Infer phase from current vault_index BEFORE building anchoring context,
    # so the anchoring summary (ADR-022) reflects the current phase.
    vault_index: dict[str, list[str]] = state.get("vault_index") or {}
    inferred_phase = infer_phase_from_vault_index(vault_index)

    working_state = (
        compact_context(state, CONTEXT_LIMIT)
        if should_compact(state, CONTEXT_LIMIT)
        else state
    )
    anchoring = build_anchoring_context(state)
    messages: list[BaseMessage] = [SystemMessage(content=full_prompt)]
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    messages.extend(working_state.get("messages", []))

    # ... model invocation and route parsing (unchanged) ...

    return {"next": next_route, "pipeline_phase": inferred_phase}
```

Key integration constraints:

- `infer_phase_from_vault_index` is called **before** `build_anchoring_context` so
  the anchoring summary injected at position [2] already reflects the current phase.
- `pipeline_phase` is included in every supervisor return dict, including the early-
  return path for unparseable responses and the FINISH-blocked path.
- `pipeline_phase` uses last-write-wins semantics (ADR-019 §2.1). Each supervisor
  invocation overwrites with the latest inference — no accumulation needed.

### 2.3 Phase Advance Mechanism via vault_index Propagation

Phase advances automatically as a natural consequence of artifact writes. No explicit
"advance phase" call is needed anywhere in the system. The full chain:

1. A worker writes a new artifact (e.g., `.vault/exec/auth-flow-step-001.md`) and
   returns `{"vault_index": {"exec": [".vault/exec/auth-flow-step-001.md"]}}` in
   its node return dict.
2. The `_merge_vault_index` reducer (ADR-019 §2.2) merges the new path into
   `state["vault_index"]["exec"]`.
3. On the next supervisor invocation, `infer_phase_from_vault_index(state["vault_index"])`
   finds `vault_index["exec"]` is non-empty → returns `"exec"`.
4. Supervisor returns `{"next": worker, "pipeline_phase": "exec"}` → `pipeline_phase`
   in `TeamState` is updated to `"exec"`.
5. On the worker's next invocation:
   - ADR-022 anchoring includes `**Phase:** exec` in the summary at position [2].
   - ADR-020 `mount_node` selects exec-phase documents from `vault_index["exec"]`
     for injection at position [3].
   - ADR-021 `_filter_queue_content` activates (phase is `"exec"` ∈ `{"plan", "exec"}`).

**The key architectural insight:** `pipeline_phase` is derived from artifact state,
not declared by any agent. Workers do not need to announce "I have entered the exec
phase." They simply write an exec artifact and return the updated `vault_index` entry.
The phase signal propagates automatically through the `_merge_vault_index` reducer
and `infer_phase_from_vault_index` inference on the subsequent supervisor call.

This design aligns with the blackboard control-unit pattern (arXiv 2507.01701):
the control unit (supervisor) observes the blackboard (vault_index) and computes
phase — it does not receive phase as input from knowledge sources (workers).

### 2.4 First Session and Session Restart Behaviour

**First session (no prior artifacts):**

At graph compilation for a new thread, `_build_initial_vault_index` (ADR-019 §2.4)
scans `.vault/` for files matching `active_feature`. If the feature is brand new,
no matching files exist. `vault_index = {}` is set in `graph_input`. On the first
supervisor invocation, `infer_phase_from_vault_index({})` returns `"research"` —
the correct starting phase for a feature with no artifacts.

**Session restart (new thread, same feature, existing artifacts):**

If a feature already has artifacts on disk (e.g., from a previous thread), the
`_build_initial_vault_index` scan at graph compilation will find and index them.
`vault_index` is populated from disk before the first supervisor call.
`infer_phase_from_vault_index` then infers the correct phase from the existing
artifacts — the session resumes at the phase the feature has reached, not at
`"research"`.

This behaviour requires no special handling. The same inference function that
advances phase during a session also correctly restores phase on session restart.

### 2.5 Edge Cases and Accepted Trade-offs

**Deliberate phase regression (human asks for more research after ADRs exist):**

If an operator instructs the supervisor to do additional research after ADR
documents already exist in `vault_index["adr"]`, the inferred phase remains
`"adr"` — not `"research"`. Consequence: ADR documents are injected at position
[3] alongside the research work. This is slightly suboptimal (the worker sees ADR
docs it may not need) but not incorrect — ADR documents are binding references and
seeing them during extended research is acceptable. The worker's task instructions
from the supervisor override any phase-based expectations. Accepted for v1.

**Plan → exec transition moment (first exec invocation, no exec artifacts yet):**

When the supervisor first routes a worker to begin execution work, `vault_index["exec"]`
is empty. The inferred phase is `"plan"`. Consequence: plan documents are injected
at position [3] — appropriate context for a worker beginning to translate a plan
into execution steps. The phase advances to `"exec"` after the first exec artifact
is written and its path is merged into `vault_index`. Accepted for v1.

**`vault_index` not updated after artifact writes:**

If a worker writes a `.vault/exec/` artifact but forgets to return
`{"vault_index": {"exec": [new_path]}}`, the `vault_index` is not updated and
the phase does not advance. This is a node implementation responsibility, not a
failure of the phase inference mechanism. ADR-019 §3 documents this as an
accepted trade-off of the reference-in-state pattern.

## 3. Consequences

### Positive

- **Deterministic and zero-cost:** `infer_phase_from_vault_index` is a pure Python
  function with O(6) complexity. It adds no token overhead, no LLM call, and no
  filesystem I/O to the supervisor invocation.
- **Self-correcting:** Phase is recomputed from `vault_index` on every supervisor
  call. It cannot drift out of sync with artifact state as long as workers correctly
  update `vault_index` when writing artifacts.
- **First session correct by default:** Empty `vault_index` → `"research"` with no
  special-case handling.
- **Session restart correct by default:** `_build_initial_vault_index` rebuilds
  `vault_index` from disk; inference restores the correct phase automatically.
- **Unblocks ADR-020, ADR-021, ADR-022 downstream consumers:** All three ADRs gain
  a correctly populated `pipeline_phase` on every invocation.
- **Aligns with blackboard control-unit pattern:** Phase is observed from blackboard
  state (vault_index), not produced by knowledge sources (workers/LLM).

### Negative / Trade-offs

- **Deliberate phase regression not supported:** If an operator wants to re-enter
  `"research"` after ADR artifacts exist, the inferred phase stays at `"adr"`. The
  only way to override is to remove ADR entries from `vault_index` explicitly (not
  supported in v1). Operators must be aware that phase is artifact-driven.
- **Transition-moment lag:** Phase advances only after the first artifact of the new
  phase is written. The initial invocation of a new phase operates at the previous
  phase's document set. For most use cases this is appropriate (plan docs are
  correct context when beginning exec), but it means there is no way to "declare
  exec has started" without writing an artifact.
- **Depends on workers updating vault_index:** If workers write artifacts without
  returning `vault_index` updates, the phase will not advance. This is a contract
  that must be enforced by worker node implementation and tested.

## 4. Rejected Alternatives

### Option B — LLM Outputs Phase as Part of Routing

The supervisor LLM returns a structured `{next: str, phase: str}` output. Rejected
for the following reasons:

1. **Hallucination risk on a structurally binding field.** `pipeline_phase` gates
   document selection (ADR-020), queue injection (ADR-021), and anchoring content
   (ADR-022). A hallucinated phase value (e.g., `"implementation"` instead of
   `"exec"`, or skipping `"plan"` entirely) cascades into wrong documents being
   injected on every subsequent worker invocation.
2. **All surveyed frameworks avoid LLM phase determination.** MetaGPT uses a
   deterministic role-sequencing cursor. CrewAI uses task-order (sequential) or
   delegation (hierarchical) — neither involves LLM phase output. The blackboard
   paper (2507.01701) explicitly places phase determination in the control unit,
   not in knowledge sources.
3. **Adds structured output constraint to the supervisor.** Requiring
   `with_structured_output` on the supervisor restricts which models can serve
   in that role and adds latency. The current supervisor uses text parsing for
   routing — extending to structured output is a non-trivial change with no
   correctness benefit over Option A.

### Option C — Hybrid (Deterministic Baseline, LLM Can Advance)

The deterministic inference provides a floor; the LLM can advance phase forward
(but not backward). Rejected for v1 because:

1. **Narrow benefit.** The only scenario where Option C outperforms Option A is
   the transition moment between phases — the single supervisor invocation that
   routes the first worker of a new phase before any artifact has been written.
   This is one invocation out of potentially hundreds; the document injection
   suboptimality (previous phase docs) is minor.
2. **Added complexity.** Requires a structured output schema on the supervisor,
   a forward-only tiebreaker comparison using `PHASE_ORDER`, and test coverage
   for the tiebreaker paths.
3. **Can be layered on later.** `PHASE_ORDER` is exported from `lib/core/phase.py`
   specifically to support a future Option C implementation without changing the
   public API. The tiebreaker logic can be added to `create_supervisor_node()` in
   a future ADR without breaking existing callers.

### Phase Set Once at Graph Compilation

Computing phase once at `compile_team_graph()` and storing it in `graph_input`
produces a stale value for the entire session. A session that begins at `"plan"`
and writes exec artifacts would never advance to `"exec"`. Rejected.

### Phase Stored in DB / ThreadMetadata

`ThreadMetadata` is immutable after creation (ADR-014 §3). Phase must track runtime
progression — it cannot be stored in an immutable DB record. Rejected.

## 5. Implementation Constraints

- `lib/core/phase.py` must declare `__all__ = ["PHASE_ORDER", "infer_phase_from_vault_index"]`.
  The module-internal constant `_PHASE_ORDER` is an alias for `PHASE_ORDER` and is
  not exported.
- `infer_phase_from_vault_index` must be a pure function — no I/O, no LangGraph
  imports, no side effects. It must be testable in isolation.
- `infer_phase_from_vault_index` must be called on every `supervisor_node` invocation,
  before `build_anchoring_context` is called.
- The result must appear as `pipeline_phase` in every supervisor return dict — including
  the early-return path for unparseable responses and the FINISH-blocked-by-validation-
  errors path.
- `pipeline_phase` valid values are restricted to the six entries in `PHASE_ORDER`:
  `"research"`, `"reference"`, `"adr"`, `"plan"`, `"exec"`, `"audit"`. No other
  values may be written to `TeamState["pipeline_phase"]` by this mechanism.
- `PHASE_ORDER` in `lib/core/phase.py` is the single authoritative definition of
  pipeline phase order. No other module may define or duplicate this list.
- `lib/core/__init__.py` must export `infer_phase_from_vault_index` per the facade
  pattern (CLAUDE.md architectural patterns).

## 6. Module Hierarchy Impact

```text
lib/core/
├── phase.py            NEW: PHASE_ORDER, infer_phase_from_vault_index;
│                       __all__ = ["PHASE_ORDER", "infer_phase_from_vault_index"]
├── nodes/
│   └── supervisor.py   AMENDED: imports infer_phase_from_vault_index;
│                       calls it on every invocation before build_anchoring_context;
│                       returns {"next": route, "pipeline_phase": inferred_phase, ...}
│                       in all return paths
├── __init__.py         AMENDED: export infer_phase_from_vault_index (facade pattern)
├── tests/
│   ├── test_phase.py   NEW: all branches of infer_phase_from_vault_index —
│   │                   empty vault_index, single phase, highest-wins, all phases,
│   │                   audit wins over exec, first-session "research" default
│   └── test_supervisor.py  AMENDED: verify pipeline_phase present in supervisor
│                           return dict on normal route, FINISH, and error paths
```

## 7. References

- `lib/core/phase.py` — NEW (infer_phase_from_vault_index, PHASE_ORDER)
- `lib/core/nodes/supervisor.py` — AMENDED (phase inference on every invocation)
- `lib/core/__init__.py` — AMENDED (facade export)
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) — pipeline_phase field definition,
  vault_index reducer, \_build_initial_vault_index
- [ADR-020](020-blackboard-content-mounting.md) — \_select_paths uses pipeline_phase
  for phase-scoped document selection
- [ADR-021](021-persistent-task-queue-schema.md) — queue injection gated on
  pipeline_phase in {"plan", "exec"}
- [ADR-022](022-contextual-anchoring-graph-lifecycle.md) — build_anchoring_context
  includes pipeline_phase in anchoring summary
- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md)
  — DRIFT-11: pipeline_phase never set at runtime
- [docs/research/2026-03-03-pipeline-phase-population-research.md](../research/2026-03-03-pipeline-phase-population-research.md)
  — framework analysis, options evaluation, Option A recommendation
- [arXiv 2507.01701](https://arxiv.org/abs/2507.01701) — blackboard control unit as
  observer of blackboard state, not knowledge source
- [MetaGPT arXiv 2308.00352](https://arxiv.org/abs/2308.00352) — deterministic
  role-sequencing, orchestrator owns phase transitions
