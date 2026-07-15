---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# `model-profiles` `P02` summary

Two steps wired model profiles into the gateway surface end to end: the presets-list discovery record was extended with full profile and eligibility disclosure using the same shared resolver launch uses (S03), and run-start gained profile validation, freeze-and-persist, restart-safe reuse, and atomic idempotency against concurrent same-`run_id` retries (S04). A code-review fold-in commit (d362c16) closed the MEDIUM-1 race condition and a LOW path-leakage in reason strings across both steps.

- Modified: `src/vaultspec_a2a/api/routes/gateway.py`
- Modified: `src/vaultspec_a2a/api/schemas/gateway.py`
- Modified: `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- Modified: `src/vaultspec_a2a/team/team_config.py`
- Modified: `src/vaultspec_a2a/providers/model_profiles.py`
- Modified: `src/vaultspec_a2a/providers/tests/test_model_profiles.py`
- Modified: `src/vaultspec_a2a/graph/compiler.py`
- Modified: `src/vaultspec_a2a/graph/tests/test_compiler.py`
- Modified: `src/vaultspec_a2a/control/dispatch.py`
- Modified: `src/vaultspec_a2a/control/thread_service.py`
- Modified: `src/vaultspec_a2a/ipc/schemas.py`
- Modified: `src/vaultspec_a2a/worker/graph_lifecycle.py`

## Description

S03 (3affc9e + a27e228 source refinement) extended presets-list into a full model-profile discovery record. New schemas `RoleAssignmentSummary` and `ProfileSummary` carry safe operational metadata only: role and agent ids, provider id, capability, stable concrete model name, ordered fallbacks, provider readiness, source attribution, and eligibility with safe reasons. `PresetSummary` gained `origin` (bundled/workspace/test_mock), `supported_capabilities` (research_adr → `research_document` + `architecture_decision`), `profiles`, and `default_profile_id`. The endpoint probes engine reachability once and offloads the full build off the event loop via `asyncio.to_thread`; `_summarize_profiles` resolves every profile through the same `resolve_effective_assignment` launch uses, sharing one provider-readiness cache. One invalid preset still yields one unavailable record with its origin retained. The `RoleAssignment.source` field was refined in a follow-up commit (a27e228) to report the topmost influencing layer — a capability-only profile overlay is disclosed as `profile` rather than hiding behind the provider's lower-layer source. Eligibility is reported honestly: with the production acceptance gate open (P04.S10 not passed) and the authoring engine absent from the test environment, every profile is served `eligible=false` with safe reasons rather than a false positive, matching the ADR's honesty requirement. The discovery-versus-launch acceptance-gate refinement is now pinned in the ADR: the gate is a discovery-certification signal surfaced by presets-list; it is not a launch blocker (see S04 notes).

S04 (ced69d1 + d362c16 MEDIUM-1 fold-in) integrated profiles into the run verbs. `RunStartRequest.profile_id` defaults to `team-defaults` with a bounded validator; both `RunStartResponse` and `RunStatusResponse` gained additive `profile_id` and `assignments` disclosure reusing `RoleAssignmentSummary`. `FrozenAssignment`, `freeze_assignment`, and `frozen_from_record` were added to `providers/model_profiles.py`; `compiler_map()` yields the provider/capability/fallback subset the compiler consumes. The run-start endpoint validates the profile belongs to the preset (422 unknown) and is runnable, gating on provider readiness only — the acceptance gate and engine reachability are discovery-certification signals, not launch blockers. The effective assignment is frozen with a sha256 digest, persisted as a `model_profile` key in the existing thread-metadata JSON, and threaded to dispatch. A retry that changes the frozen profile returns a typed 409; a same-profile retry is the idempotent replay; the verb never silently falls back to `team-defaults`. The frozen map threads through `DispatchRequest` → `graph_lifecycle` → `compile_team_graph` (all four topology builders) → `_resolve_worker_model_preferences`, which short-circuits to `_parse_frozen_preferences` when a worker is named, tolerant of agent-config drift. `redispatch_reconciling_threads` rebuilds from persisted metadata so a restarted run recompiles the exact launched models. Run-status discloses the frozen profile and assignments reproduced from run metadata, never re-resolved. The review fold-in (d362c16) closed the MEDIUM-1 race: the create-and-dispatch is now insert-or-return atomic — an `IntegrityError` from the losing racer is caught, the session rolled back, and the winner's run returned as the dispatch-exactly-once response. A concurrency test fires five simultaneous same-`run_id` requests and asserts none 5xx, all resolve to one run, and exactly one dispatch. The LOW finding was also closed: exception-derived reason strings that could embed local filesystem paths are replaced by a `_safe_load_reason` category switch and by logging rather than serving the classifier exception from the command-unresolvable path.

## Verification

All scoped suites green at phase close. S03: 2 new live presets-list tests (truthful/resilient full disclosure, workspace-origin preset with profile); S02 resolver suite (15) unaffected after the source refinement. S04: 4 `FrozenAssignment` unit cases, 2 compiler frozen-consumption cases, 3 live gateway cases (freeze+disclose+dispatch+run-status, unknown-profile 422, profile-change 409 + same-profile replay), plus the 5-concurrent idempotency test from the fold-in. Full default suite 1503 passed. `ruff check`, `ruff format`, and `ty check` clean across all touched files. No mocks; no secrets in any served or persisted record (asserted).
