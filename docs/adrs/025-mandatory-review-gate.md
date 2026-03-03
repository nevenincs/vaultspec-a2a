---
adr_id: 025
title: Mandatory Review Gate
date: 2026-03-03
status: Implemented
related:
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/022-contextual-anchoring-graph-lifecycle.md
  - docs/adrs/026-pipeline-phase-population.md
---

# ADR-025: Mandatory Review Gate

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

D-03 and D-13 from the vaultspec rule drift audit identify the same gap from
two angles:

- **D-03:** No automatic review invocation in graph routing. The supervisor can
  route to FINISH after an executor completes without ever invoking a reviewer
  agent.
- **D-13:** The graph has no structural gate preventing a worker from returning
  and the supervisor routing directly to FINISH without a reviewer having been
  invoked.

The existing `validation_errors` FINISH gate (ADR-022 §2.4) blocks on
malformed artifacts but does not enforce review. A thread can complete with
valid artifacts that have never been reviewed. This violates the vaultspec SDD
mandate that every execution phase must be followed by an audit phase before
completion.

This ADR adds a second FINISH gate — firing after the `validation_errors` gate
— that checks for review artifact presence via `vault_index["audit"]`
(introduced in ADR-019). When no review artifact exists and exec work has been
done in an SDD-bound thread, FINISH is blocked and the supervisor is rerouted
to invoke a reviewer agent.

## 2. Decision

### 2.1 Gate Condition

Three conditions must ALL hold for FINISH to be blocked:

1. `active_feature` is set — SDD context is active (gate is irrelevant without
   a feature).
2. `vault_index["exec"]` is non-empty — execution work has been done and a
   review is therefore required.
3. `vault_index["audit"]` is empty — no review artifact has been produced yet.

When all three conditions hold, FINISH is blocked and the supervisor reroutes
to `workers[0]` with a `routing_error` message that clearly states a review
artifact is required. The supervisor LLM is expected to interpret this message
and route to the appropriate reviewer agent.

### 2.2 Implementation Location

The gate extends the existing `if next_route == "FINISH"` block in
`supervisor_node` (`lib/core/nodes/supervisor.py`), following the same pattern
as the ADR-022 `validation_errors` gate. It fires **after** the
`validation_errors` check:

```python
if next_route == "FINISH":
    # Existing gate: validation errors (ADR-022)
    errors: list[str] = state.get("validation_errors") or []
    if errors:
        next_route = workers[0]
        return {"next": next_route, "pipeline_phase": inferred_phase,
                "routing_error": f"FINISH blocked: {len(errors)} validation error(s)"}

    # ADR-025 gate: review artifact required when feature is active and exec phase reached
    active_feature = state.get("active_feature")
    vault_index = state.get("vault_index") or {}
    if active_feature and vault_index.get("exec") and not vault_index.get("audit"):
        next_route = workers[0]
        return {"next": next_route, "pipeline_phase": inferred_phase,
                "routing_error": "FINISH blocked: no review artifact in vault_index[\"audit\"]. "
                                 "A reviewer agent must produce an audit artifact before completion."}
```

No new node types or edge types are introduced. The gate is a pure extension of
the existing conditional return-path logic in `supervisor_node`.

### 2.3 Execution Order

Two sequential checks are applied on the FINISH path:

1. **`validation_errors` gate (ADR-022)** — blocks on malformed artifacts.
   Fires first because malformed artifacts are a more immediate concern than
   missing review artifacts.
2. **Review artifact gate (ADR-025)** — blocks when no review artifact is
   present in `vault_index["audit"]`.

Both must pass for FINISH to proceed. Either gate independently can block
completion and trigger a reroute.

### 2.4 `autonomous=True` Behaviour

The gate is **not** bypassed in autonomous mode. Review enforcement is a
quality mandate — autonomous runs that skip review produce unreviewable
outputs. The `autonomous=True` flag bypasses permission interrupts for tool
calls; it does not imply that unreviewed work is acceptable.

This is consistent with the `validation_errors` gate (ADR-022 §2.4), which
also applies unconditionally in autonomous mode.

### 2.5 No `active_feature` Behaviour

When `active_feature` is `None`, the gate is skipped entirely. The thread is
not SDD-bound; the review mandate does not apply. This is the correct
behaviour for ad-hoc chat threads that are not part of a feature development
workflow.

## 3. Consequences

### Positive

- Structural enforcement that review always occurs before completion in
  SDD-bound threads where execution work has taken place.
- Consistent with the existing FINISH gate pattern (ADR-022) — no new node
  types or edge types are required.
- Works identically in both interactive and autonomous modes; the quality
  mandate is never silently bypassed.

### Negative / Trade-offs

- Depends on the vault_index update contract (ADR-019 §3): workers that write
  review artifacts **must** return `{"vault_index": {"audit": [path]}}` to
  register the artifact. If they do not, the gate blocks incorrectly even
  when a review artifact exists on disk.
- v1 checks only that `vault_index["audit"]` is non-empty, not that the
  artifact follows a specific naming convention (e.g., `{feature}-review.md`).
  A future v2 can enforce the naming convention once the review workflow is
  stable. Any audit artifact is treated as sufficient evidence of review in
  v1.
- The gate reroutes to `workers[0]`, which may not be a reviewer agent. The
  mechanism relies on the supervisor LLM interpreting the `routing_error`
  message and selecting the correct agent. This is intentional — dynamic
  routing is the star topology's primary mechanism; hardcoding a specific
  reviewer worker index would undermine it.

### Edge Cases

| Scenario                                                          | Gate behaviour                                    | Acceptable?                                       |
| ----------------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------- |
| No `active_feature`                                               | Gate skipped                                      | Yes — non-feature threads are out of SDD scope    |
| `active_feature` set, no exec artifacts yet                       | Gate skipped (exec non-empty check fails)         | Yes — if no execution happened, no review needed  |
| `active_feature` set, exec artifacts exist, audit artifacts exist | FINISH allowed                                    | Yes — review artifact present                     |
| `active_feature` set, exec artifacts exist, no audit artifacts    | FINISH blocked, reroute                           | Yes — this is the enforcement case                |
| Multiple exec→review cycles (iterative review)                    | Each FINISH attempt checks `vault_index["audit"]` | Yes — gate passes once any review artifact exists |
| Review artifact written but not added to `vault_index`            | Gate blocks incorrectly                           | Risk — workers must return `vault_index` updates  |

## 4. Rejected Alternatives

### Dedicated Review Graph Node (MetaGPT-style mandatory QA role)

MetaGPT's pipeline always ends with a `QAEngineer` role; the orchestrator
hard-codes the role sequence so QA cannot be skipped. This is structurally
clean but incompatible with our star topology, which uses dynamic routing
rather than a fixed pipeline. Adding a mandatory review node before END would
require structural graph changes: new node registration, new conditional edges,
and modification of `compile_team_graph()`. Rejected in favour of the lighter
FINISH gate pattern already established by ADR-022.

### Specific Artifact Name Matching (`*{feature}*review*`)

Option B from the research (§2.1): check that at least one entry in
`vault_index["audit"]` matches `*{active_feature}*review*` before allowing
FINISH. This is more specific and aligns with the vaultspec mandate (D-14:
review artifact at `.vault/exec/{feature}/{feature}-review.md`). Deferred to
v2 — artifact naming conventions are not yet stable enough to encode as a gate
condition. Any audit artifact is sufficient evidence of review in v1.

## 5. Implementation Constraints

- The gate lives in `supervisor_node` return-path logic, not in a new graph
  node or conditional edge function.
- The gate fires **after** the `validation_errors` gate (ADR-022), before
  FINISH is returned.
- The `routing_error` message must clearly state that a review artifact is
  required, so the supervisor LLM can select an appropriate reviewer agent.
- No changes to `TeamState` schema are required — the gate uses existing
  `vault_index` and `active_feature` fields (ADR-019).
- `vault_index` and `active_feature` are read with `.get()` inside the gate
  because `supervisor_node` may be invoked on legacy state that pre-dates
  ADR-019 (defensive reads only at this call site; required fields elsewhere).
  This is a deliberate exception to ADR-019 §5's "no `.get()`" mandate —
  supervisor gate code must tolerate legacy checkpoints where the migration
  backfill has not yet run.

## 6. Module Hierarchy Impact

```text
lib/core/
  nodes/supervisor.py   AMENDED: second FINISH gate in supervisor_node,
                        after the validation_errors check (ADR-022 §2.4)

  tests/test_graph.py   AMENDED: test cases for review gate —
                        verify FINISH is blocked when active_feature set +
                        exec non-empty + audit empty; verify FINISH proceeds
                        when audit non-empty; verify gate skipped when
                        active_feature is None
```

## 7. References

- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — D-03, D-13, D-14
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) — `vault_index`
  structure and vault_index update contract (§3 accepted trade-off)
- [ADR-022](022-contextual-anchoring-graph-lifecycle.md) — existing
  `validation_errors` FINISH gate (§2.4); gate pattern this ADR extends
- [ADR-026](026-pipeline-phase-population.md) — `inferred_phase` in supervisor
  return dict
- [docs/research/2026-03-03-mandatory-review-gate-research.md](../research/2026-03-03-mandatory-review-gate-research.md) — prior art analysis, gate mechanism recommendation, edge case table
- MetaGPT arXiv 2308.00352 — mandatory QA role in fixed pipeline
- `lib/core/nodes/supervisor.py` — existing FINISH gate implementation
