---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Enforce state and status discipline with live tests and a rag-first sweep for violations: LangGraph state carries only Rust-backend identifiers for authoring (session, changeset, proposal ids), never content or tokens, and product-facing status speaks role and phase vocabulary rather than internal node names

## Scope

- `src/vaultspec_a2a/thread/state.py`
- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/worker/tests/`

## Description

- Sweep rag-first, then read, the LangGraph state and the product status contract for discipline violations.
- Confirm the authoring state fields carry only Rust-backend identifiers and rely on the existing reducer coverage; add nothing redundant.
- Fix the one status violation found: map the product active-position field to role vocabulary and remove the internal node-name projection from the product topology contract.
- Add real assertions that the product status never leaks a node name.

## Outcome

State discipline: already clean and covered. The authoring correlation fields hold only the session id and the changeset and proposal id lists — a comment on the fields forbids content, and there is no token field (per-agent token accounting is integer counters; role tokens live in the separate run token store, not state). The de-duplicating reducer for the id lists is already exercised by real assertions in the state tests, so no new state code or test was needed. The transient mounted-context field is read-input under an earlier decision, cleared after the worker reads it, and is not authoring state.

Status discipline: one real violation, now fixed. The product run-status endpoint exposed internal LangGraph node names — the topology carried a raw next-node list, and the active-position helper returned the raw node name for supervisor and gate stages. Both are replaced: a new helper maps the active node to the role of the matching agent, so worker positions read as their role while internal orchestration and gate nodes resolve to none rather than leaking a node name; per-role state and the pause cause carry the rest. Real assertions cover the mapping (worker to role, mount prefix stripped, orchestration node to none, empty and end skipped) and the contract shape (the product topology has no node-name field, the role field remains).

Dated decision note (2026-07-15): the field ``next_nodes`` was DROPPED from the version-one product topology contract. Rationale: it leaked internal node names into product status, which the production-wiring amendment forbids, and the run-status contract is required to speak position in role terms; the removal was taken now, deliberately, while the field has no external consumer, because the engine pass-through that would wrap it is unbuilt — after that consumer exists the same change becomes a reviewed cross-repo contract event. Where the datum survives: the raw next-node projection is retained UNCHANGED in the internal recovery snapshot (`thread/snapshots.py` and its serialization schema), which recovery reads; only the product surface was narrowed. Architect concurrence recorded at assignment.

## Notes

- No state source changed: the discipline was already met and asserted; adding a redundant field or test would be noise.
- The active-position semantics changed at the boundary: during internal orchestration or gate stages the product active-position is now none rather than a node name. This is intended — no agent role is active then, and the roles list plus pause cause remain expressive.
- Coordinated with the sibling submitter step on the session keying and state-shape questions; the document body stays in the message channel and never enters authoring state, and any revision-cycle counter, if needed, would be an integer field, discipline-clean.
