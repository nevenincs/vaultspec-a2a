---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S05'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# Run the handover evidence battery live: bundled plus workspace discovery, mock marking, invalid-preset isolation, heterogeneous team-defaults disclosure, missing-credential unavailable profile, fallback eligibility, unknown-profile rejection, frozen assignment surviving restart and config drift, no secrets anywhere, and a real research-to-ADR run on the served assignments

## Scope

- `src/vaultspec_a2a/service_tests/`
- `src/vaultspec_a2a/api/tests/`

## Description

Added the net-new live evidence for the handover battery that the P02 gateway
tests did not already cover, in a dedicated module `test_model_profiles_evidence.py`
under `api/tests/`. Every check runs against real production code paths - the real
gateway over a real TCP socket, the real durable SQLite thread store and
AsyncSqliteSaver checkpointer, the real shared resolver and readiness probe, and
real settings read from a spawned process environment. No mocks, monkeypatch,
stubs, or skips.

- Prove a frozen profile survives a genuine gateway restart: freeze on a first
  app instance, then read run-status from a second app instance built on the same
  durable stores; the assignment is reproduced verbatim and nothing re-dispatches.
- Prove workspace config drift after launch does not mutate a running run: rewrite
  the workspace profile capability after freeze; run-status still discloses the
  frozen value.
- Prove discovery and launch resolve through the one canonical
  `resolve_effective_assignment` object and disclose byte-identical per-role
  assignments for the same team and profile.
- Prove the persisted run-metadata DB row carries the frozen profile but no actor
  token, bearer, or credential marker.
- Prove a scrubbed-credential spawned process reports an unavailable provider with
  a safe, secret-free reason; a credential injected into that same process env
  flips readiness ready (real settings, not a monkeypatch of the running one).
- Prove a ready declared fallback makes an unready-primary role eligible while a
  no-fallback control role is not, over the real readiness probe.

## Outcome

- Created: `src/vaultspec_a2a/api/tests/test_model_profiles_evidence.py`

New tests: 7 passed. Full `api/tests` suite: 194 passed. `ruff check`, `ruff
format --check`, and whole-tree `ty check src/vaultspec_a2a` all clean.

### Evidence table

| tmp3 verification item | Where proven | Result |
| --- | --- | --- |
| Discovery returns bundled + workspace-local presets | `test_gateway_live.py::test_presets_list_discloses_workspace_profile_origin` (P02) | covered |
| Mock/test presets explicitly identified | `test_gateway_live.py::test_presets_list_is_truthful_and_resilient` (P02) | covered |
| One invalid preset -> one unavailable record | `test_gateway_live.py::test_presets_list_is_truthful_and_resilient` (P02) | covered |
| ADR-research required roles + document capabilities | `test_gateway_live.py::test_presets_list_is_truthful_and_resilient` (P02) | covered |
| team-defaults resolves heterogeneous role assignments | `test_gateway_live.py::test_presets_list_is_truthful_and_resilient` (P02) | covered |
| Provider readiness evaluated without exposing secrets | `test_presets_list_is_truthful_and_resilient` + `test_run_start_persists_no_secrets_in_db_row` | covered |
| Missing credential -> unavailable profile, safe reason | `test_missing_credential_yields_unavailable_with_safe_reason` (spawned env) | S05 new |
| Eligible fallback makes role/profile eligible | `test_eligible_fallback_makes_role_eligible` (spawned env, real probe) | S05 new |
| Unknown/unavailable profile rejected by run-start | `test_gateway_live.py::test_run_start_rejects_unknown_profile` (P02) | covered |
| Selected profile + frozen assignment survive restart | `test_frozen_assignment_survives_real_gateway_restart` | S05 new |
| Workspace default change after launch does not mutate run | `test_workspace_drift_after_launch_does_not_mutate_run` | S05 new |
| Discovery and launch use the same resolution path | `test_discovery_and_launch_resolve_through_one_function` (identity + equal output) | S05 new |
| No secrets in responses/logs/checkpoints/DB rows | responses: P02 tests; DB row: `test_run_start_persists_no_secrets_in_db_row`; checkpoints: see Notes | partial |
| A real Research -> ADR run on served assignments | P04.S10 (separate executor, own engine) | referenced |

## Notes

- Present-credential readiness uses a dummy, non-secret Zhipu value injected only
  into the spawned process env; every probe asserts the value never appears in
  output. The spawned probe runs with its working directory at an empty temp dir
  so pydantic-settings loads no repository `.env`, guaranteeing a deterministic
  credential state regardless of the host developer's environment.
- Checkpoint secret-freedom is asserted at the DB-row level here; the gateway does
  not write graph checkpoints in these tests (the in-process worker only records
  the dispatch), so checkpoint content is produced only by a real graph run. That
  path is exercised by the P04.S10 acceptance run, which owns the real
  Research -> ADR execution on the served assignments; this record references that
  evidence rather than duplicating it.
- The identity check asserts both gateway call sites bind to the single
  module-level `resolve_effective_assignment`; a runtime call-count spy would
  require monkeypatching (forbidden), so identity is evidenced structurally plus by
  byte-identical disclosed assignments from the discovery and launch endpoints.
