# SDD Cross-Document Consistency Audit

**Updated:** 2026-03-03
**Auditor:** codebase-researcher
**Scope:** All SDD/blackboard/vaultspec-alignment ADRs (019–026), research docs (9), audit tracker docs (2), rule drift doc (1)
**Total findings:** 18 (3 HIGH, 5 MEDIUM, 10 LOW)

---

## HIGH Findings

### C-01 — CONTRADICTION — ADR-019 §2.1 vs §2.2: "required" vs `NotRequired`

- **Doc A:** ADR-019 §2.1 — "All four fields are required on every TeamState"
- **Doc B:** ADR-019 §2.2 code block — `active_feature: NotRequired[str]`
- **Description:** The prose and the normative code block within the same ADR directly contradict each other. Implementation follows `NotRequired`. The "required" guarantee is enforced by `graph_input` initialisation at thread creation, not by TypedDict syntax — this architectural nuance is undocumented.
- **Status:** Open — requires ADR-019 amendment
- **Fix:** Amend ADR-019 §2.1 and §5 to clarify: "required" means always set in `graph_input` at thread creation; `NotRequired` is the correct Python typing for fields that may not be present in legacy checkpoints. Add a note explaining the distinction.

---

### C-02 — CONTRADICTION — ADR-019 §5 vs implementation-notes §3 + ADR-026 §2.2: `.get()` usage

- **Doc A:** ADR-019 §5 — "Nodes read SDD fields via direct access: `state['active_feature']`" (no `.get()`)
- **Doc B:** implementation-notes §3 + ADR-026 §2.2 pseudocode — both use `state.get("key")`
- **Description:** ADR-019 §5 prohibits `.get()`. Implementation notes and ADR-026 pseudocode both use `.get()`. ADR-025 §5 also uses `.get()` with an explicit legacy-state carve-out. Three sources conflict on the same access pattern.
- **Status:** Open — requires ADR-019 amendment
- **Fix:** ADR-019 §5 should be updated to acknowledge the `.get()` carve-out: for `NotRequired` fields, `.get()` is required to handle legacy checkpoints that predate ADR-019. This supersedes the "direct access" mandate for scalar fields.

---

### C-03 — CONTRADICTION — gap-analysis `vault_index: dict[str, str]` vs ADR-019 `dict[str, list[str]]`

- **Doc A:** `2026-03-03-sdd-blackboard-gap-analysis.md` §3.2 — `vault_index: dict[str, str]`
- **Doc B:** ADR-019 §2.2 — `vault_index: dict[str, list[str]]`
- **Description:** Research proposed wikilink-keyed flat mapping. ADR decided on doc-type → list-of-paths. Gap analysis was never updated. Any developer reading it gets the wrong type signature.
- **Status:** Open — requires gap analysis doc update
- **Fix:** Add "Decision" header note to gap analysis §3.2: "Superseded by ADR-019 §2.2. Final type: `dict[str, list[str]]`."

---

## MEDIUM Findings

### C-04 — CONTRADICTION — `reference` gate: research SOFT vs ADR-023 None

- **Doc A:** `2026-03-03-phase-artifact-gates-research.md` §2 — `reference: SOFT gate (warn but allow)`
- **Doc B:** ADR-023 §2.1 — `reference: None (no gate, supporting phase)`
- **Status:** Open — requires research doc header note
- **Fix:** Add superseded note to research doc §2.

---

### C-05 — CONTRADICTION — plan rejection path: research FINISH vs ADR-024 `workers[0]`

- **Doc A:** `2026-03-03-plan-approval-interrupt-research.md` §2.2 Option A — rejection routes to `FINISH`
- **Doc B:** ADR-024 §2.4 — rejection routes to `workers[0]`
- **Status:** Open — requires research doc header note
- **Fix:** Add superseded note to research doc §2.2.

---

### C-06 — CONTRADICTION — DRIFT-05/D-11 classification inconsistency between trackers

- **Doc A:** `sdd-alignment-tracker.md` — DRIFT-05 "By design (supervisor to populate)"
- **Doc B:** `vaultspec-rule-drift.md` — D-11 "MEDIUM open drift"
- **Description:** Both docs describe the same gap (`pipeline_phase` never set). ADR-026 now resolves it. Neither tracker marked it resolved.
- **Status:** Open — both trackers need update
- **Fix:** Mark DRIFT-05 and D-11 as ✅ Resolved by ADR-026 in both documents.

---

### I-01 — INCONSISTENCY — ADR status fields in `sdd-alignment-tracker.md` inconsistent

- **Description:** ADR-019 and ADR-022 listed as "Implemented" in Active ADRs table without "auditing" suffix, while ADRs 020–026 show "Implemented, auditing". ADR-019/022 were also audited (Cycles 1 and 2) and have open drift items.
- **Status:** Open — tracker needs update
- **Fix:** Update ADR-019 and ADR-022 status to "Implemented, auditing" for consistency.

---

### I-02 — INCONSISTENCY — `_infer_phase_from_vault_index` private in research vs public in ADR-026

- **Doc A:** `2026-03-03-pipeline-phase-population-research.md` §2 — `_infer_phase_from_vault_index` (private)
- **Doc B:** ADR-026 §2.2 + `src/vaultspec_a2a/core/phase.py` — `infer_phase_from_vault_index` (public, exported)
- **Status:** Open — research doc update
- **Fix:** Add note to research doc §2 that function was made public in final ADR.

---

## LOW Findings

### C-07 — `active_task_id` (research) vs `current_task_id` (ADR-021/implementation)

### C-08 — Task ID format `P{N}-S{N}` (research) vs `{PREFIX}-{NNN}` (ADR-021)

### C-09 — `_mount_blackboard()` (research) vs `create_mount_node()` (ADR-020)

### I-03 — "mount step" (research) vs "mount node" (ADR-020) terminology

### I-04 — `autonomous=True` gate bypass framing (research §2.3 misleading heading)

### D-01 — ADR-025 §2.2 pseudocode is verbatim copy of mandatory-review-gate research §2.2

### D-02 — ADR-024 §2.2 pseudocode is verbatim copy of plan-approval research Option A

### D-03 — ADR-023 §2.1 gate table is verbatim copy of phase-artifact-gates research §3

### S-01 — external-research §5 "No Direct Open-Source Precedent" — no actionable content

### S-02 — sdd-alignment-tracker.md "Continuous Audit Scope" checklist partially redundant with drift table

---

## ADR-024 Conformance Drifts (from codebase-researcher audit)

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| DRIFT-A | MEDIUM | No test for approve resume path — `Command(resume={"approved": True})` → `plan_approved: True` → routes to exec worker | Open |
| DRIFT-B | MEDIUM | No test for reject resume path — `Command(resume={"approved": False})` → routes to `workers[0]` with routing_error | Open |
| DRIFT-C | LOW | `aggregator.py` uses `PermissionOptionKind.REJECT_ONCE` — ADR-024 §2.3 specifies `DENY_ONCE` | Open |

---

## Documents Internally Consistent (No Changes Needed)

- ADR-020, ADR-021, ADR-023, ADR-025, ADR-026 — internally consistent, no cross-doc contradictions in normative ADR corpus
- ADR-024 — internally consistent (one LOW implementation drift in aggregator.py, not a doc conflict)
- ADR-022 — internally consistent; C-02 is between ADR and research/notes doc, not within ADR corpus

---

## Priority Action Plan

| Priority | Action | Target doc(s) |
|----------|--------|---------------|
| HIGH | Amend ADR-019 §2.1 + §5 — resolve "required" vs `NotRequired` contradiction, clarify `.get()` carve-out | ADR-019 |
| HIGH | Add superseded note to gap analysis §3.2 — correct `vault_index` type | gap-analysis |
| MEDIUM | Mark DRIFT-05 / D-11 resolved in both tracker docs | sdd-alignment-tracker, vaultspec-rule-drift |
| MEDIUM | Add superseded notes to research docs (C-04, C-05, I-02) | 3 research docs |
| MEDIUM | Update ADR-019/022 status in alignment tracker | sdd-alignment-tracker |
| LOW | Add superseded notes for stale function/field names (C-07/08/09, I-03) | research docs |
