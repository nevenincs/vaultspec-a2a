---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S24'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Reshape the gateway into the five versioned verbs (run-start, run-status, run-cancel, presets-list, service-state), designing run-status as the authoritative recovery snapshot with topology position, per-role state, and produced proposal ids

## Scope

- `src/vaultspec_a2a/api/`

## Description

Reshape the existing gateway surface into the five versioned verbs the engine
pass-through forwards, per ADR R6. Commit `86b53ac`.

Created: `src/vaultspec_a2a/api/schemas/gateway.py`,
`src/vaultspec_a2a/api/routes/gateway.py`.

Modified: `src/vaultspec_a2a/api/routes/__init__.py`,
`src/vaultspec_a2a/control/thread_state_service.py`.

- Mount `run-start`, `run-status`, `run-cancel`, `presets-list`, and
  `service-state` under `/v1` as the engine-facing edge. Each verb reshapes an
  existing service rather than reinventing it, so there is a single code path:
  the richer internal `/api` surface and the verbs call the same services.
- `run-start` is the reshaped thread-create plus first message, accepting the R7
  actor token bundle and delegating to `create_and_dispatch_thread`.
- `run-status` is the authoritative recovery snapshot: topology position (preset,
  active agent stripped of its mount prefix, next nodes, pause cause), per-role
  lifecycle state, and the engine proposal and changeset ids the run produced,
  read from the checkpoint by the new `read_run_authoring_ids` helper, plus the
  checkpoint cursor and repair posture.
- `run-cancel` delegates to the already-idempotent cancel service; `presets-list`
  and `service-state` roll up preset listing and the health/doctor status.
- Every response carries an explicit `api_version` and bounded fields so the
  engine can wrap it verbatim under its pass-through caps.

## Outcome

Complete. `ruff` and `ty` clean. The existing internal `/api` suite passes
unchanged (218 passed), confirming the reshape added the edge without disturbing
the internal surface. A live-socket smoke over the real app returned 200 for
`GET /v1/presets` with `api_version: v1`. Full live coverage of all five verbs
lands in S25.

## Notes

This FastAPI build (0.139.0 / starlette 1.3.1) mounts a prefixed router as a
sub-application, so the `/v1` routes do not appear flattened in `app.routes`;
they are reached correctly at request time (verified by a real request), a
harmless introspection quirk worth knowing for anyone auditing the route table.

The internal `/api` surface is retained as internal-only per the governing ADR's
consequences; it is not deleted here.
