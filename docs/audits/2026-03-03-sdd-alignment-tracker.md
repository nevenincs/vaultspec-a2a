# SDD Alignment Tracker

**Updated:** 2026-03-03
**Scope:** Ongoing audit of agent definitions, team definitions, and codebase against SDD/blackboard ADRs (019, 022, and pending 020, 021).

---

## Active ADRs (Binding)

| ADR     | Title                                             | Status                |
| ------- | ------------------------------------------------- | --------------------- |
| ADR-019 | TeamState Enrichment for SDD Blackboard Awareness | Implemented           |
| ADR-022 | Contextual Anchoring in Graph Lifecycle           | Implemented           |
| ADR-020 | Blackboard Content Mounting                       | Implemented, auditing |
| ADR-021 | Persistent Task Queue Schema                      | Implemented, auditing |
| ADR-023 | Phase Artifact Gates                              | Implemented, auditing |
| ADR-024 | Plan Approval Interrupt                           | Implemented, auditing |
| ADR-025 | Mandatory Review Gate                             | Implemented, auditing |
| ADR-026 | pipeline_phase Population                         | Implemented, auditing |

---

## Audit Cycles

### Cycle 1 — 2026-03-03 (ADR-019 + ADR-022 conformance)

**Auditor:** codebase-researcher
**Result:** 7 gaps found, 2 fixed (GAP-01 imperative anchoring, GAP-06 discover_context_refs 4→6 stages). GAP-02/03/04 by design (infrastructure ready, population is future node work).

### Cycle 2 — 2026-03-03 (Full 3-area audit: TOML + graph + nodes)

**Auditor:** codebase-researcher
**Result:** 4 new drift items (DRIFT-07 through DRIFT-10). 11 PASS checks.

**Area 1 — Agent TOML Presets:**

- DRIFT-07 (HIGH): No `{{FEATURE_CONTEXT}}` placeholder in any supervisor TOML directive. Affects 3 star/pipeline_loop presets. Fallback append path works but presets cannot control placement.
- PASS: No hardcoded feature names/paths.
- PASS: Persona directives reference ADR/research/plan awareness.

**Area 2 — Graph Compilation:**

- DRIFT-08 (MEDIUM): `compile_team_graph()` missing `feature_tag` parameter per ADR-019 S2.3. Fields threaded via `DispatchRequest` instead — intent satisfied, API shape deviates.
- PASS: `_build_initial_vault_index()` matches ADR-019 S2.4.
- PASS: `_VAULT_STAGE_PATTERNS` matches 6-stage spec.
- PASS: `DispatchRequest` carries all 4 SDD fields.
- PASS: `create_thread_endpoint()` sets all 4 fields.

**Area 3 — Core Nodes:**

- PASS: Supervisor anchoring at position [1] (ADR-022 S2.3).
- PASS: Worker anchoring at position [1] (ADR-022 S2.5).
- PASS: Validation error FINISH gate active (ADR-022 S2.4).
- DRIFT-09 (LOW): `anchoring.py` and `supervisor.py` use `.get()` for SDD fields — ADR-019 S5 mandates `state["field"]` direct access.
- DRIFT-10 (LOW): `TeamState` declares SDD fields as `NotRequired` — ADR-019 S2.1 says they are required fields.
- PASS: `_build_supervisor_prompt()` supports `feature_context` + `{{FEATURE_CONTEXT}}`.
- PASS: `build_anchoring_context()` uses imperative anchoring language.
- PASS: `_ANCHOR_PATH_CAP = 10` matches ADR-022.

---

## Continuous Audit Scope

### 1. Agent Definitions (`lib/core/presets/teams/*.toml`)

Check each TOML agent preset for:

- [ ] `{{FEATURE_CONTEXT}}` placeholder present in supervisor prompts (ADR-022 §2.1)
- [ ] Persona directives reference active feature awareness
- [ ] No hardcoded feature names or paths

### 2. Team Definitions

Check team graph compilation for:

- [ ] `feature_tag` parameter threaded into `compile_team_graph()` (ADR-019 §2.3)
- [ ] All 4 SDD fields set in `graph_input` at thread creation
- [ ] `_build_initial_vault_index` called when `feature_tag` present

### 3. Core Codebase (`lib/core/`)

- [ ] `discover_context_refs` covers all 6 `.vault/` stages (✅ fixed 2026-03-03)
- [ ] `build_anchoring_context` uses imperative language (✅ fixed 2026-03-03)
- [ ] `supervisor_node` FINISH gate active (✅ ADR-022)
- [ ] `worker_node` anchoring injection at position [1] (✅ ADR-022)
- [ ] Mount node exists and is wired (❌ pending ADR-020)
- [ ] Task queue parsed and injected (❌ pending ADR-021)

### 4. `.vaultspec` Rule Drift

Track divergence between `.vaultspec` rules in `Y:/code/vaultspec-worktrees/main/.vaultspec/` and the engine's actual behaviour. Delivered by docs-researcher-2 to orchestrator each cycle.

---

## Open Drift Items

| ID       | Source     | Description                                                                                            | Severity | Status                             |
| -------- | ---------- | ------------------------------------------------------------------------------------------------------ | -------- | ---------------------------------- |
| DRIFT-01 | .vaultspec | `discover_context_refs` missing `reference` + `audit` stages                                           | HIGH     | ✅ Fixed                           |
| DRIFT-02 | .vaultspec | Anchoring instruction passive, not imperative                                                          | MEDIUM   | ✅ Fixed                           |
| DRIFT-03 | .vaultspec | No mount step — agents see paths, not content                                                          | HIGH     | ✅ Fixed (ADR-020 implemented)     |
| DRIFT-04 | .vaultspec | No persistent task queue — agents track state implicitly                                               | HIGH     | ✅ Fixed (ADR-021 implemented)     |
| DRIFT-05 | ADR-022    | `pipeline_phase` never set at runtime                                                                  | MEDIUM   | ✅ Fixed (ADR-026 implemented)     |
| DRIFT-06 | ADR-019    | `vault_index` not updated after artifact writes                                                        | MEDIUM   | By design (node responsibility)    |
| DRIFT-07 | ADR-022    | No `{{FEATURE_CONTEXT}}` placeholder in any supervisor TOML directive (3 presets affected)             | HIGH     | ✅ Fixed                           |
| DRIFT-08 | ADR-019    | `compile_team_graph()` missing `feature_tag` param — fields threaded via DispatchRequest instead       | MEDIUM   | ✅ Fixed                           |
| DRIFT-09 | ADR-019    | `anchoring.py` + `supervisor.py` use `.get()` for SDD fields instead of direct `state["field"]` access | LOW      | ✅ Resolved (ADR-019 §5 clarified: `.get()` is acceptable for legacy checkpoint tolerance) |
| DRIFT-10 | ADR-019    | `TeamState` SDD fields declared `NotRequired` — ADR says required                                      | LOW      | ✅ Resolved (ADR-019 §5 clarified: `NotRequired` for TypedDict compat, semantically required via graph_input) |

---

## Known Trade-offs (Not Drift)

| ID          | Source  | Description                                                                                                                                                                                                                                                    | Rationale                                                                                                                                                                                                                 |
| ----------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TRADEOFF-01 | ADR-026 | `pipeline_phase` one-invocation lag: `infer_phase_from_vault_index` computes the phase before `build_anchoring_context`, but the value only enters `TeamState` via the supervisor's return dict. Anchoring reads the _previous_ invocation's `pipeline_phase`. | Same class as transition-moment lag (ADR-026 §2.5). Fixable by passing inferred phase to `build_anchoring_context` as parameter override (changes ADR-022 signature). Deferred — one-invocation lag is acceptable for v1. |
