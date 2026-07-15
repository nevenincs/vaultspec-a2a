---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S04'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# Integrate profiles into run-start and run-status: validate profile belongs to preset, reject unknown or ineligible profiles with typed responses, freeze and persist the effective assignment with digest in run metadata, reuse frozen assignment on restart, disclose profile and assignments in responses

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/control/`
- `src/vaultspec_a2a/database/`

## Description

Integrated model profiles into the run-start and run-status verbs end to end.

- Request/response schemas (`api/schemas/gateway.py`): `RunStartRequest.profile_id` (default `team-defaults`, bounded); additive `profile_id` + `assignments` disclosure on both `RunStartResponse` and `RunStatusResponse` (reusing the S03 `RoleAssignmentSummary`).
- Freeze + persistence (`providers/model_profiles.py`): `FrozenAssignment` (safe per-role record + sha256 digest), `freeze_assignment`, and `frozen_from_record`; `compiler_map()` yields the provider/capability/fallback subset the compiler consumes.
- run-start endpoint (`api/routes/gateway.py`): validate the profile belongs to the preset (422 unknown) and is runnable (422 ineligible - launch gates on provider readiness only; the acceptance gate and engine reachability are discovery-certification signals, not launch blockers); freeze the effective assignment; persist `{profile_id, digest, roles}` into the thread metadata JSON; thread the frozen map to dispatch; disclose profile + assignments. A retry that changes the frozen profile returns a typed 409 conflict; a same-profile retry is the idempotent replay. Never silently falls back to team-defaults.
- Restart reuse: the frozen assignment threads through `ThreadCreationRequest` -> `DispatchRequest.{profile_id, model_assignment}`; `graph/compiler.py` consumes it verbatim (`_resolve_worker_model_preferences` short-circuits to `_parse_frozen_preferences` when a worker is named, tolerant of drift), threaded through all four topology builders and `compile_team_graph`; `control/dispatch.redispatch_reconciling_threads` rebuilds the frozen map from persisted metadata so a restarted run recompiles the exact launched models.
- run-status endpoint discloses the frozen profile + assignments reproduced from run metadata (never re-resolved).

## Outcome

Green on its owned surface: `ruff`/`format`/`ty` clean across all eight touched files. New tests, all passing: 4 `FrozenAssignment` freeze/round-trip/digest cases; 2 compiler frozen-consumption cases (verbatim override + absent-worker fall-through); 3 live gateway cases (freeze+disclose+dispatch-carries-assignment+run-status disclosure; unknown-profile 422 with no dispatch; profile-change-retry 409 with same-profile replay). The graph suite is unchanged (frozen defaults to None = byte-identical). No mocks; no secrets in any served or persisted record (asserted).

## Notes

Launch-eligibility semantics: run-start rejects unknown and provider-unavailable profiles but does not enforce the open acceptance-gate term (that would refuse every run), keeping the gate a discovery-certification signal surfaced by presets-list. Restart reuse reads the same persisted `model_profile` record run-status discloses; the redispatch read mirrors the run-status read (both proven readable). Persistence embeds the frozen record as a `model_profile` key in the existing thread-metadata JSON (ThreadMetadata is `extra=ignore`, and production reads it as raw JSON), avoiding a new DB column.

### Review fold-in (MEDIUM-1)

Code review flagged that run-start idempotency was check-then-act (`get_thread` then create), so simultaneous same-`run_id` retries could race into a primary-key collision 500 instead of returning the existing run. Landed as a follow-up (the S04 code was already committed): the create-and-dispatch is now insert-or-return atomic - an `IntegrityError` from the losing racer's insert is caught, the session rolled back, and the winner's run returned as the dispatch-exactly-once response (with its persisted profile disclosed). A concurrency test fires five simultaneous same-`run_id` requests and asserts none 5xx, all resolve to the one run, and the worker dispatched exactly once.
