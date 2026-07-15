---
tags:
- '#adr'
- '#phase-artifact-gates'
date: 2026-03-03
modified: '2026-07-15'
related:
- '[[2026-03-03-teamstate-enrichment-sdd-blackboard-adr]]'
- '[[2026-03-03-contextual-anchoring-graph-lifecycle-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `phase-artifact-gates` adr: `adr-19` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-19`
- Original title: `Phase Artifact Gates`
- Legacy status at migration time: `Implemented`

## Original ADR

## ADR-023: Phase Artifact Gates

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

D-01 from the vaultspec rule drift audit: the supervisor can route workers to
any phase without checking that prerequisite artifacts exist. The vaultspec
framework (`framework.md`) defines an explicit dependency graph between phases:

```text
research → adr → plan → exec → audit
```text

Without prerequisite enforcement, the supervisor can route:

- A planner worker before any ADR exists — producing an ungrounded plan with
  no binding architectural decision.
- An executor worker before any plan exists — the highest-risk gap, execution
  with no approved direction.
- An auditor worker before any execution has taken place — reviewing
  non-existent outputs.

These out-of-order transitions produce ungrounded artifacts, waste compute,
and silently violate the SDD pipeline contract. No existing gate in
`supervisor_node` checks phase prerequisites before committing to a routing
decision.

## 2. Decision

### 2.1 Gate Table

The following table translates the framework dependency chain into
`vault_index` checks (ADR-019). Supporting phases (`reference`, `curate`) are
orthogonal to the main pipeline and are not gated.

| Target phase | Required `vault_index` entry        | Strictness | Rationale                                                                                                   |
| ------------ | ----------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------- |
| `research`   | None                                | —          | Starting phase, no prerequisites                                                                            |
| `reference`  | None                                | —          | Supporting phase, invoked at any time                                                                       |
| `adr`        | `vault_index["research"]` non-empty | SOFT       | Framework requires research artifact, but ADRs from direct knowledge are legitimate — warn without blocking |
| `plan`       | `vault_index["adr"]` non-empty      | HARD       | Planning without a binding ADR produces an ungrounded plan                                                  |
| `exec`       | `vault_index["plan"]` non-empty     | HARD       | Execution without an approved plan is the highest-risk gap                                                  |
| `audit`      | `vault_index["exec"]` non-empty     | HARD       | Reviewing non-existent execution is meaningless                                                             |

**SOFT gate:** Allow routing to proceed; add a warning to `routing_error` in
state and log at WARNING level. The supervisor LLM can observe the warning on
its next pass.

**HARD gate:** Block routing; set `routing_error` in state explaining the
missing prerequisite. The routing decision (`next_route`) is preserved as the
supervisor's intent — the supervisor LLM determines the recovery route on its
next invocation.

**Why `adr` is SOFT, not HARD:** The framework marks research as a
prerequisite for ADRs, but in practice ADRs are legitimately written from
direct knowledge, design discussions, or as records of existing architectural
decisions. Blocking ADR creation without formal research would prevent valid
use cases. The soft gate surfaces a warning without enforcing.

**Why `reference` has no gate:** The framework explicitly describes reference
as "supporting, invoked when appropriate" — it is orthogonal to the main
pipeline and can be called at any phase to audit external codebases.

### 2.2 Gate Mechanism

The gate extends `supervisor_node` (`src/vaultspec_a2a/core/nodes/supervisor.py`), firing
after all FINISH gates (ADR-022, ADR-025) and before the final routing
decision is returned. A `worker_phase_map: dict[str, str]` (worker id →
pipeline phase) is provided at `create_supervisor_node()` compilation time:

```python
# After route parsing and FINISH gates in supervisor_node...
target_phase = worker_phase_map.get(next_route)
if target_phase and active_feature:
    gate_result = _check_phase_prerequisites(target_phase, vault_index)
    if gate_result.blocked:
        return {"next": next_route, "pipeline_phase": inferred_phase,
                "routing_error": gate_result.message}
    elif gate_result.warning:
        logger.warning(gate_result.message)
        # soft gate — routing proceeds, warning surfaced in state via routing_error
        return {"next": next_route, "pipeline_phase": inferred_phase,
                "routing_error": gate_result.message}
```text

`_check_phase_prerequisites` is a new private function in `supervisor.py`
that encapsulates the gate table logic, returning a result with `blocked:
bool`, `warning: bool`, and `message: str`.

### 2.3 SOFT vs HARD Gate Behaviour

**HARD gate (plan, exec, audit):**

- The routing decision is preserved (`next_route` is not changed) — the
  supervisor's intent is recorded in state.
- `routing_error` is set with a message explaining the missing prerequisite
  artifact.
- On the next supervisor invocation, `routing_error` is present in state and
  can be surfaced to the supervisor LLM via `build_anchoring_context` (ADR-022
  §2.1), prompting it to route to a prerequisite-producing worker instead.
- The gate does **not** auto-reroute. Which worker to invoke to satisfy a
  missing prerequisite is a routing judgment — the supervisor LLM decides.

**SOFT gate (adr):**

- Routing proceeds unchanged.
- `routing_error` is set with a warning message (observable by the supervisor
  on next pass).
- A WARNING-level log entry is emitted.

### 2.4 `worker_phase_map` Derivation

The `worker_phase_map` is derived from team TOML presets at graph compilation
time. Each worker's role/skill designation maps to a pipeline phase. Workers
without an explicit phase mapping are exempt from phase gating — the gate
defaults to no-op for unmapped workers (conservative: do not block routing
decisions the gate does not understand).

`compile_team_graph()` (`src/vaultspec_a2a/core/graph.py`) builds the map from preset
metadata and passes it to `create_supervisor_node()` alongside the existing
`workers: list[str]` parameter.

### 2.5 No `active_feature` Behaviour

All phase artifact gates are skipped when `active_feature` is `None`. The
thread is not SDD-bound; the phase prerequisite mandate does not apply. This
is consistent with the ADR-025 review gate and the ADR-022 validation gate —
all quality gates are scoped to SDD-active threads.

### 2.6 Interaction with ADR-026

ADR-026 (pipeline phase population) determines `pipeline_phase` by observing
`vault_index` — the highest phase with existing artifacts. ADR-023 checks
prerequisites for the supervisor's _routing target_, not the inferred phase.
These are complementary and non-conflicting:

- **ADR-026:** "What phase are we currently in?" → Answered by vault_index
  observation.
- **ADR-023:** "Can the supervisor route to this target phase right now?" →
  Answered by prerequisite check against vault_index.

A routing decision to `exec` is gated on `vault_index["plan"]` being
non-empty regardless of what `pipeline_phase` is currently set to. The gate
is stateless with respect to `pipeline_phase` — it checks vault_index
directly.

## 3. Consequences

### Positive

- Prevents out-of-order phase transitions (exec without plan, audit without
  exec) at the routing level, before a worker is invoked.
- The soft gate for `adr` allows legitimate direct-knowledge ADRs while still
  surfacing a visible warning in state.
- No new graph nodes or edge types — the gate extends existing supervisor
  return-path logic, consistent with ADR-022 and ADR-025.
- Works in both interactive and autonomous modes; gate is not bypassed by
  `autonomous=True`.

### Negative / Trade-offs

- Requires `worker_phase_map` as a new parameter for `create_supervisor_node()`
  and `compile_team_graph()`. Team presets must carry sufficient role metadata
  for the mapping to be derivable at compilation time.
- Mixed-phase workers (a single worker capable of both plan and exec) require
  a multi-phase mapping or explicit gate exemption. The v1 design assumes
  single-phase workers.
- HARD gate blocking does not auto-reroute — it relies on the supervisor LLM
  interpreting the `routing_error` message and selecting an appropriate
  prerequisite-producing worker. If the LLM ignores the error, the same route
  will be blocked repeatedly.

### Edge Cases

| Scenario                                                   | Gate behaviour                                                           |
| ---------------------------------------------------------- | ------------------------------------------------------------------------ |
| No `active_feature`                                        | All gates skipped — non-feature threads outside SDD scope                |
| Worker has no phase mapping                                | Gate skipped for that worker (conservative default)                      |
| Routing to `research`                                      | No gate — always allowed as starting phase                               |
| Routing to `reference`                                     | No gate — supporting phase, invoked at any time                          |
| Routing to `adr` with no research artifacts                | SOFT gate — warning in `routing_error`, routing allowed                  |
| Routing to `plan` with no ADR artifacts                    | HARD gate — `routing_error` set, routing preserved but blocked           |
| Routing to `exec` with no plan artifacts                   | HARD gate — highest-risk gap; also intersects with ADR-024 plan approval |
| Routing to `audit` with no exec artifacts                  | HARD gate — reviewing non-existent execution blocked                     |
| Routing to `exec` with plan artifacts but no plan approval | Handled by ADR-024 (plan approval interrupt) — separate gate             |

## 4. Rejected Alternatives

### Separate Gate Node Between Supervisor and Mount Node

Insert a `phase_gate_node` in the graph between the supervisor's conditional
edge and the `mount_{agent_name}` node. Rejected: this adds another node per
worker in an already-complex graph (mount nodes per ADR-020) with no new
capability. The gate has full access to `vault_index` in `TeamState` — a
separate node adds graph complexity for no functional gain.

### Gate in `_infer_phase_from_vault_index` (ADR-026)

Co-locate phase inference and prerequisite checking in the same function.
Rejected: `_infer_phase_from_vault_index` answers "what phase are we in?"
(observational). The gate answers "can we route to this target phase?"
(prescriptive). These are distinct concerns; mixing them violates single
responsibility and makes `_infer_phase_from_vault_index` harder to reason
about and test independently.

### Auto-Reroute to Prerequisite-Producing Worker

When a hard gate blocks, automatically reroute to the worker whose phase
produces the missing prerequisite (inverts `worker_phase_map`). Deferred to
v2: in teams with multiple workers per phase (e.g., two researcher workers),
the auto-reroute target is ambiguous. The supervisor-decides approach is less
prescriptive but avoids the ambiguity. Can be revisited once team topologies
are more standardised.

## 5. Implementation Constraints

- The gate lives in `supervisor_node`, after all FINISH gates (ADR-022
  validation_errors gate, ADR-025 review artifact gate), before returning the
  routing decision.
- `worker_phase_map: dict[str, str]` is provided at `create_supervisor_node()`
  compilation time, following the same pattern as the existing `workers:
list[str]` parameter.
- The gate is stateless with respect to `pipeline_phase` — it checks
  `vault_index` directly.
- Workers without a phase mapping in `worker_phase_map` are exempt from
  gating (conservative default — do not block unknown workers).
- `_check_phase_prerequisites()` is a private function in `supervisor.py`,
  not exposed via `__all__`.

## 6. Module Hierarchy Impact

```text
src/vaultspec_a2a/core/
  nodes/supervisor.py   AMENDED: phase prerequisite gate after FINISH gates;
                        new _check_phase_prerequisites() private function;
                        create_supervisor_node() gains worker_phase_map param

  graph.py              AMENDED: compile_team_graph() derives worker_phase_map
                        from team TOML presets and passes to
                        create_supervisor_node()

  tests/test_graph.py   AMENDED: test cases for phase gates —
                        HARD block (plan/exec/audit without prerequisites),
                        SOFT warn (adr without research),
                        gate skip (no active_feature, unmapped worker)
```text

## 7. References

- legacy-audits/2026-03-03-vaultspec-rule-drift.md — D-01
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md` — authoritative pipeline prerequisite table
- ADR-019 — `vault_index` structure and update contract
- ADR-022 — existing `validation_errors` FINISH gate pattern
- ADR-025 — review artifact FINISH gate (same pattern extended here)
- ADR-026 — `pipeline_phase` inference (complementary, not conflicting)
- legacy-research/2026-03-03-phase-artifact-gates-research.md — gate table derivation, mechanism options, edge case analysis
- `src/vaultspec_a2a/core/nodes/supervisor.py` — existing FINISH gate implementation reference

## Amendment - a2a-edge-conformance (2026-07-15)

The phase gate now tests PROPOSAL existence and approval through the engine
authoring API, not files appearing under `.vault/`. A phase's artifact is
present when its whole-document proposal exists on the changeset (and, for
the exec gate, when the plan proposal was approved) - the filesystem cannot
see unapplied proposals (dashboard D4). This aligns with the queue-by-
reference model (W02.S13) and the run-local generalized document gate (W03).
See `2026-07-14-a2a-edge-conformance-adr` (R12) and
`2026-07-14-a2a-edge-conformance-reference`.
