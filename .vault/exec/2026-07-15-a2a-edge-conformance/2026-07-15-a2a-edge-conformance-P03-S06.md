---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S06'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# Run the handover live evidence battery (refusal matrix, idempotent retry same-run, restart recovery, degraded service-state under dependency failures, SSE reconnect, engine pass-through) and document the verb-to-legacy-service mapping with an explicit legacy-route retirement path

## Scope

- `src/vaultspec_a2a/service_tests/`
- `src/vaultspec_a2a/api/tests/`
- `docs/`

## Description

- Ran the handover live evidence battery over real in-process infrastructure (a
  uvicorn socket, a real SQLite thread store, a real AsyncSqliteSaver
  checkpointer, and the conftest in-process worker over real HTTP) - no mocks.
- Added a degraded-service-state evidence test: tripping the real worker circuit
  breaker open makes service-state report alive but not can_accept_run, status
  degraded, circuit_breaker open, and the failure named in degraded_reasons.
- Added a reconnect-cursor evidence test: run-status serves the monotonic
  last_sequence, the durable reconnect cursor, so a client reconciles from
  run-status rather than the droppable SSE progress stream.
- Documented the verb-to-legacy-service mapping and the legacy /api route
  retirement path in a docs file, including where each v1 verb intentionally
  diverges from its /api sibling (run-start refusals + idempotency, presets-list
  truthfulness, service-state probe-derived status).

## Outcome

Live evidence (all pass over real in-process infra):

- Refusal matrix: empty prompt, missing/unloadable preset, document-authoring
  preset without a feature, and incomplete token bundle all 422 pre-dispatch
  (test_run_start_refusals_over_live_socket).
- Idempotent retry same-run: a client run_id dispatches exactly once across a
  retry (test_run_start_client_id_is_dispatch_exactly_once).
- Restart recovery: multi-role run-status recovery with zero vault writes
  (test_multirole_run_status_recovery_and_zero_vault_writes).
- Tokens absent from logs/serialized surfaces
  (test_run_start_carries_no_token_into_logs).
- Degraded service-state under a real dependency failure (open circuit) -> new
  test above.
- SSE: versioned frames mid-stream, semantic-phase stamping, document-body
  bounding to the drop sentinel; reconnect reconciles from run-status
  last_sequence -> new cursor test above.
- Full in-process battery green: 13 tests (11 existing + the 2 added).

Not run (reported with the exact reason, per the live-infra mandate):

- The Docker-compose service_tests (full worker-subprocess lifecycle, cancel,
  permissions-resume, stream-followup) and the full live Rust-backend engine
  pass-through are NOT RUN: the Docker daemon is not reachable in this
  environment (docker version -> "cannot connect to the Docker API ... daemon is
  running"; the harness needs service/docker-compose.integration.yml). These are
  marked `service` and deselected by the default `-m "not service"`; they require
  the compose stack to be brought up on a host with a running Docker daemon.

## Notes

- Engine pass-through and the Rust-backend loopback round-trip are proven
  elsewhere by the verdict-subscriber live suite (P03.S07/S08 of the
  orchestration plan) against a resident engine; this Step's edge battery proves
  the gateway surface over in-process infra and defers the compose-stack
  pass-through to a Docker-enabled host.
- The verb-to-legacy-service mapping and the staged /api retirement path are in
  docs/a2a-edge-conformance-verb-mapping.md; the service functions beneath the
  verbs are shared implementation and are retained, not retired.
