---
title: 'Research: Mandatory Review Gate'
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: 'How to enforce mandatory review agent invocation before FINISH. Analysis of prior art and recommended gate mechanism for ADR-025.'
---

# Research: Mandatory Review Gate

**Date:** 2026-03-03

## Summary

D-03 and D-13 in the vaultspec rule drift audit identify the same gap from two angles:

- **D-03:** No automatic review invocation in graph routing. Supervisor may route to FINISH after an executor completes without invoking a reviewer agent.
- **D-13:** The graph has no structural gate preventing a worker from returning and the supervisor routing to FINISH without a reviewer having been invoked.

The `validation_errors` FINISH gate (ADR-022 §2.4) already blocks FINISH when errors are non-empty. ADR-025 extends this pattern with a second FINISH gate: check for review artifact presence in `vault_index["audit"]` before allowing completion.

---

## 1. Prior Art

### 1.1 MetaGPT QA Role

MetaGPT's pipeline always ends with a `QAEngineer` role. The orchestrator's role sequence is hard-coded: `ProductManager → Architect → ProjectManager → Engineer → QAEngineer`. The QA role cannot be skipped — it is not gated by a condition check; it simply always executes as the final node in the sequence.

**Key lesson:** The simplest enforcement is structural — make review a mandatory graph node. However, MetaGPT's fixed pipeline is simpler than a star topology with dynamic routing. In a star topology, the supervisor can route to FINISH at any step. A structural fix requires either (a) a conditional edge that forces a review node before END, or (b) a FINISH gate that checks for review evidence.

### 1.2 CrewAI Task Dependencies

CrewAI supports `task.context = [prior_task]` to declare that a task requires the output of a prior task. In hierarchical process, the manager LLM can be constrained by a `full_output` flag that forces all tasks to complete before any output is returned. Neither mechanism enforces that a specific "review" task was called — they enforce sequencing, not content.

**Key lesson:** CrewAI's dependency model is task-level, not artifact-level. It would require a hard-coded "review task" as a dependency of the final task. This maps to our star topology as: the FINISH gate checks that a review task produced an artifact, rather than checking that a specific node was traversed.

### 1.3 LangGraph Conditional Edges and Gate Nodes

LangGraph's canonical pattern for enforcing pre-conditions on FINISH is to add logic in the conditional edge function. The current supervisor already uses this pattern for the `validation_errors` gate:

```python
if next_route == "FINISH":
    errors = state.get("validation_errors") or []
    if errors:
        next_route = workers[0]  # reroute instead of finishing
```

Extending this to a review artifact check is a natural continuation of the same pattern — no new node type is required. The gate lives in `supervisor_node`'s return-path logic.

### 1.4 Existing FINISH Gate (ADR-022 §2.4)

The current gate in `supervisor_node`:

```python
if next_route == "FINISH":
    errors: list[str] = state.get("validation_errors") or []
    if errors:
        next_route = workers[0]
        return {"next": next_route, "routing_error": f"FINISH blocked: {len(errors)} validation error(s)"}
```

This is the exact pattern ADR-025 should extend. The review artifact gate becomes a second condition on the same `if next_route == "FINISH"` branch.

---

## 2. Gate Mechanism Recommendation

### 2.1 What the Gate Should Check

**Option A: Any entry in `vault_index["audit"]`**

`vault_index["audit"]` is non-empty → review artifact exists → FINISH allowed.

Pros: Simple, consistent with how all other phases are tracked. `vault_index["audit"]` is populated by `_build_initial_vault_index` at graph compilation and by worker nodes that write audit artifacts and return the updated vault_index entry.

Cons: Does not distinguish between a review artifact and any other audit artifact (e.g., a general audit log). The vaultspec mandate specifies a specific artifact: `{feature}-review.md`.

**Option B: Specific artifact `{feature}-review.md` in `vault_index["audit"]`**

Check that at least one entry in `vault_index["audit"]` matches `*{active_feature}*review*`.

Pros: More specific — matches the vaultspec mandate (D-14: review artifact MUST be at `.vault/exec/{feature}/{feature}-review.md`).

Cons: Requires substring matching on path strings in vault_index, introducing a naming convention dependency. If the feature tag contains unusual characters or the review artifact is named differently, the gate fails silently or incorrectly.

**Recommendation: Option A for v1, Option B for v2.**

In v1, `vault_index["audit"]` being non-empty is sufficient evidence that a review artifact was created. The naming convention check can be added in v2 once the review workflow is more established and artifact naming is stable. Option A is consistent with how all other phase gates work (ADR-023 gate table uses non-empty checks throughout).

### 2.2 Gate Implementation

The gate extends the existing FINISH check in `supervisor_node`:

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

**Gate condition logic:**

- `active_feature` is set (SDD context is active — gate is irrelevant without a feature)
- `vault_index["exec"]` is non-empty (exec work has been done — review is required)
- `vault_index["audit"]` is empty (no review artifact exists yet)

If all three conditions hold, FINISH is blocked and the supervisor reroutes to the first available worker (which the supervisor LLM should contextually route to a reviewer agent given the routing error message).

### 2.3 `autonomous=True` Behaviour

The gate should **not** be bypassed in autonomous mode. Review enforcement is a quality and safety mandate — autonomous runs that skip review produce unreviewable outputs. The `autonomous=True` flag bypasses the permission interrupt for tool calls; it does not imply unreviewed work is acceptable.

This is consistent with the `validation_errors` gate, which also applies in autonomous mode.

### 2.4 No `active_feature` Behaviour

When `active_feature` is `None` (no SDD context — the thread is not feature-bound), the gate is skipped entirely. The engine is operating outside the SDD pipeline; the review mandate does not apply. This is the correct behaviour for ad-hoc chat threads that are not part of a feature development workflow.

---

## 3. Edge Cases

| Scenario                                                        | Gate behaviour                                  | Acceptable?                                       |
| --------------------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------- |
| No active_feature                                               | Gate skipped                                    | Yes — non-feature threads are out of SDD scope    |
| active_feature set, no exec artifacts yet                       | Gate skipped (exec non-empty check fails)       | Yes — if no execution happened, no review needed  |
| active_feature set, exec artifacts exist, audit artifacts exist | FINISH allowed                                  | Yes — review artifact present                     |
| active_feature set, exec artifacts exist, no audit artifacts    | FINISH blocked, reroute                         | Yes — this is the enforcement case                |
| Multiple exec→review cycles (iterative review)                  | Each FINISH attempt checks vault_index["audit"] | Yes — gate passes once any review artifact exists |
| Review artifact written but not added to vault_index            | Gate blocks incorrectly                         | Risk — workers must return vault_index updates    |

The last scenario is a dependency on the vault_index update contract (ADR-019 §3 accepted trade-off). Workers that write review artifacts must return `{"vault_index": {"audit": [path]}}`.

---

## 4. Interaction with ADR-022 Validation Gate

The ADR-025 gate is a second condition on the same FINISH block in `supervisor_node`. Execution order:

1. Check `validation_errors` (ADR-022) — blocks on malformed artifacts
2. Check `vault_index["audit"]` (ADR-025) — blocks when no review artifact

Both gates must pass for FINISH to proceed. The validation_errors gate fires first because malformed artifacts are a more immediate concern than missing review artifacts.

---

## 5. References

- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — D-03, D-13, D-14
- [ADR-022](../adrs/022-contextual-anchoring-graph-lifecycle.md) — existing validation_errors FINISH gate (§2.4)
- [ADR-019](../adrs/019-teamstate-enrichment-sdd-blackboard.md) — vault_index structure, vault_index update contract
- [ADR-026](../adrs/026-pipeline-phase-population.md) — inferred_phase in supervisor return dict
- MetaGPT arXiv 2308.00352 — mandatory QA role in fixed pipeline
- CrewAI task dependency model — structural task ordering
- `src/vaultspec_a2a/core/nodes/supervisor.py` — existing FINISH gate implementation
