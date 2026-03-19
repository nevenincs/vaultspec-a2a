---
title: 'Research: Phase Artifact Gates'
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: 'What prerequisite artifacts should be required before each phase transition? Gate table, mechanism, and interaction with ADR-026. Research for ADR-023.'
---

## Research: Phase Artifact Gates

**Date:** 2026-03-03

## Summary

D-01 in the vaultspec rule drift audit: the supervisor can route workers to any phase
without checking that prerequisite artifacts exist. The vaultspec framework defines
an explicit dependency graph between phases. This document establishes the gate table,
mechanism, and interaction with ADR-026 deterministic phase inference.

---

## 1. Authoritative Prerequisite Chain

From `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md`:

| Phase    | Skill              | Artifact                 | Requires          |
| -------- | ------------------ | ------------------------ | ----------------- |
| Research | vaultspec-research | `.vault/research/...`    | —                 |
| Specify  | vaultspec-adr      | `.vault/adr/...`         | Research artifact |
| Plan     | vaultspec-write    | `.vault/plan/...`        | ADR artifact      |
| Execute  | vaultspec-execute  | `.vault/exec/.../steps`  | Approved plan     |
| Verify   | vaultspec-review   | `.vault/exec/.../review` | Completed step(s) |

Supporting phases (optional, invoked when appropriate):

- **Reference** (`vaultspec-reference`): Audit external codebases. No hard prerequisite in the framework doc.
- **Curate** (`vaultspec-curate`): `.vault/` hygiene. No hard prerequisite.

**Note on naming:** The vaultspec framework uses `Specify` for what ADR-019 calls `adr`, `Execute` for `exec`, and `Verify` for `audit`. The A2A engine uses the `.vault/` directory names (`adr`, `exec`, `audit`). This research uses the engine names throughout.

---

## 2. Gate Table

Translating the framework dependency chain into vault_index checks:

| Target phase | Required vault_index entry          | Strictness | Rationale                                                                                                                                                                                               |
| ------------ | ----------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `research`   | None                                | —          | Starting phase, no prerequisites                                                                                                                                                                        |
| `reference`  | None (loose)                        | SOFT       | Framework marks reference as "supporting, invoked when appropriate" — not part of the strict chain. Can be invoked at any phase.                                                                        |
| `adr`        | `vault_index["research"]` non-empty | SOFT       | Framework says "Requires: Research artifact." However, some ADRs are written without formal research (e.g., architectural decisions from direct knowledge). Recommend soft gate: warn but do not block. |
| `plan`       | `vault_index["adr"]` non-empty      | HARD       | "Requires: ADR artifact." Planning without a binding ADR produces an ungrounded plan. Hard gate.                                                                                                        |
| `exec`       | `vault_index["plan"]` non-empty     | HARD       | "Requires: Approved plan." Execution without a plan is the highest-risk gap (also D-02 plan approval). Hard gate.                                                                                       |
| `audit`      | `vault_index["exec"]` non-empty     | HARD       | "Requires: Completed step(s)." Reviewing non-existent execution is meaningless. Hard gate.                                                                                                              |

**Soft gate:** Log a warning and add a `routing_error` to state, but allow routing to proceed.
**Hard gate:** Block routing (reroute to a different worker) and add a `routing_error` to state.

**Why `adr` is SOFT, not HARD:** The framework says "Research artifact" is required, but in practice ADRs are frequently written from direct knowledge, design discussions, or as architectural records of existing decisions. Blocking ADR creation without formal research would prevent legitimate use cases. The soft gate surfaces a warning without enforcing.

**Why `reference` has no gate:** Reference is explicitly described as "supporting, invoked when appropriate" — it is orthogonal to the main pipeline and can be called at any phase to audit external codebases.

---

## 3. Where Should the Gate Live?

### Option (a): In `supervisor_node` after route parsing

Extend the existing FINISH gate pattern. After parsing the LLM's routing decision, check whether the target phase has its prerequisites met before returning.

```python
# After route parsing in supervisor_node...
target_phase = _WORKER_TO_PHASE.get(next_route)  # map worker id → phase
if target_phase:
    gate_result = _check_phase_prerequisites(target_phase, vault_index, active_feature)
    if gate_result.blocked:
        return {"next": next_route, "pipeline_phase": inferred_phase,
                "routing_error": gate_result.message}
    elif gate_result.warning:
        # soft gate — proceed but log
        logger.warning(gate_result.message)
```text

**Pros:** Single location for all routing logic. Consistent with ADR-022 and ADR-025 gate patterns. No new graph nodes.

**Cons:** Requires a `_WORKER_TO_PHASE` mapping (worker agent id → phase it belongs to). This mapping must be provided at `create_supervisor_node()` compilation time. Star topologies with mixed-phase workers (e.g., a worker that can do both plan and exec) would need a multi-phase mapping.

### Option (b): Separate gate node between supervisor and mount_node

Insert a `phase_gate_node` between the supervisor's conditional edge and the `mount_{agent_name}` node.

**Pros:** Clean separation of concerns — routing and gating are separate nodes.

**Cons:** Adds another node per worker in the graph (already adding mount nodes per ADR-020). Increases graph complexity. The gate has the same information as the supervisor (vault_index is in state) — a separate node adds no new capability.

### Option (c): In `_infer_phase_from_vault_index` (ADR-026) — reject phase advances that skip prerequisites

**Pros:** Phase inference and prerequisite checking are co-located.

**Cons:** `_infer_phase_from_vault_index` infers the current phase from existing artifacts, not the target phase of a routing decision. The gate question ("can I route to exec?") is different from the inference question ("what phase are we in?"). Mixing them violates single responsibility. Rejected.

### Recommendation: Option (a) — Extend supervisor_node

Option (a) is consistent with the existing gate patterns (ADR-022, ADR-025). It requires one new piece: the worker-to-phase mapping. This mapping is provided at `create_supervisor_node()` compilation time, the same way `workers: list[str]` is already provided.

The worker-to-phase mapping can be derived from how workers are registered in team TOML presets — each worker has a role that maps to a pipeline phase. For presets where workers do not have explicit phases (e.g., generic workers in non-SDD topologies), the gate defaults to no-op.

---

## 4. Gate Blocking Behaviour

When a hard gate blocks:

1. The routing decision is preserved (next_route is unchanged — the supervisor's intent is recorded).
2. A `routing_error` is added to the state explaining why prerequisites are missing.
3. On the next supervisor invocation, the routing_error is present in state — `build_anchoring_context` can surface it to the supervisor, prompting it to route to a prerequisite-producing worker instead.

**Key design decision:** The gate does NOT reroute automatically. The supervisor LLM should decide what to do when its intended route is blocked. The gate provides the blocking signal; the supervisor determines the recovery route. This is less prescriptive than the `validation_errors` gate (which auto-reroutes to `workers[0]`) but more appropriate here — which worker to call to satisfy a missing prerequisite is a routing judgment.

**Alternative:** Auto-reroute to the worker whose phase produces the missing prerequisite. This is more deterministic but requires the worker-to-phase mapping to be invertible (phase → worker). In teams with multiple workers per phase (e.g., two researcher workers), the auto-reroute choice is ambiguous. Recommend supervisor-decides approach for v1.

---

## 5. Interaction with ADR-026 Phase Inference

ADR-026 determines `pipeline_phase` by observing `vault_index` — the highest phase with existing artifacts. The phase artifact gate (ADR-023) checks prerequisites for the _supervisor's routing target_, not the inferred phase.

These are complementary and non-conflicting:

- ADR-026: "What phase are we currently in?" → Answered by vault_index observation.
- ADR-023: "Can the supervisor route to this target phase right now?" → Answered by prerequisite check.

A routing decision to `exec` is gated on `vault_index["plan"]` being non-empty, regardless of what `pipeline_phase` is currently set to. Even if `pipeline_phase = "exec"` (because exec artifacts already exist from a previous step), the gate still checks prerequisites for new exec routing decisions.

The gate is stateless with respect to `pipeline_phase` — it checks vault_index directly.

---

## 6. Edge Cases

| Scenario                                                   | Gate behaviour                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| No `active_feature`                                        | All gates skipped — non-feature threads are outside SDD scope                         |
| Worker has no phase mapping                                | Gate is skipped for that worker (conservative: don't block what you don't understand) |
| Routing to `research`                                      | No gate — research is always allowed as the starting phase                            |
| Routing to `reference`                                     | No gate — supporting phase, can be called at any time                                 |
| Routing to `adr` with no research artifacts                | SOFT gate — warning added to routing_error, routing allowed                           |
| Routing to `plan` with no ADR artifacts                    | HARD gate — routing blocked, routing_error set                                        |
| Routing to `exec` with no plan artifacts                   | HARD gate — routing blocked (also triggers D-02 plan approval concern)                |
| Routing to `audit` with no exec artifacts                  | HARD gate — routing blocked                                                           |
| Routing to `exec` with plan artifacts but no plan approval | Handled by ADR-024 (plan approval interrupt) — separate gate                          |

---

## 7. References

- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — D-01
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md` — authoritative pipeline prerequisite table
- [ADR-019](../adrs/019-teamstate-enrichment-sdd-blackboard.md) — vault_index structure
- [ADR-022](../adrs/022-contextual-anchoring-graph-lifecycle.md) — existing FINISH gate pattern
- [ADR-025](../adrs/025-mandatory-review-gate.md) — review artifact FINISH gate (same pattern)
- [ADR-026](../adrs/026-pipeline-phase-population.md) — pipeline_phase inference (complementary, not conflicting)
- `src/vaultspec_a2a/core/nodes/supervisor.py` — existing gate implementation reference
