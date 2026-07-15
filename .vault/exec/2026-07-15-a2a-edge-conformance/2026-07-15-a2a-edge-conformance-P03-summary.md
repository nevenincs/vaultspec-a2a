---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# `a2a-edge-conformance` `P03` summary

One step closed the plan: the live evidence battery ran all in-process gateway tests against real SQLite, a real checkpointer, and a real in-process worker — no mocks — adding degraded-service-state and reconnect-cursor evidence cases and documenting the verb-to-legacy mapping with a staged retirement path (S06).

- Modified: `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- Created: `docs/a2a-edge-conformance-verb-mapping.md`

## Description

S06 (98bea9e) ran the handover live evidence battery over real in-process infrastructure: a uvicorn socket, a real SQLite thread store, a real `AsyncSqliteSaver` checkpointer, and the conftest in-process worker over real HTTP. Two new evidence tests were added: a degraded-service-state case (tripping the real worker circuit breaker open makes service-state report `alive` but not `can_accept_run`, `status: degraded`, `circuit_breaker: open`, and the failure named in `degraded_reasons`) and a reconnect-cursor case (run-status serves the monotonic `last_sequence` so a client reconciles durably from run-status rather than the droppable SSE stream). The verb-to-legacy-service mapping was documented in `docs/a2a-edge-conformance-verb-mapping.md`, including where each v1 verb intentionally diverges from its `/api` sibling and the staged `/api` route retirement path; the service functions beneath the verbs are shared implementation and are retained, not retired.

The full in-process gateway battery passes (13 tests: 11 existing plus the 2 added).

Not run, reported with the exact reason per the live-infra mandate: the Docker-compose service_tests (full worker-subprocess lifecycle, cancel, permissions-resume, stream-followup) and the full live Rust-backend engine pass-through are not run because the Docker daemon is not reachable in this environment (`docker version` → "cannot connect to the Docker API ... daemon is running"; the harness needs `service/docker-compose.integration.yml` on a host with a running daemon). These tests are marked `service` and deselected by the default `-m "not service"` filter; they require the compose stack to be brought up on a Docker-enabled host. Engine pass-through and the Rust-backend loopback round-trip are proven separately by the verdict-subscriber live suite (P03.S07/S08 of the orchestration plan) against a resident engine.

## Verification

In-process battery green (13 tests). `ruff check`, `ruff format`, and `ty check` clean. No mocks. Docker-gated service_tests deferred to a Docker-enabled host as documented above; the in-process coverage is exhaustive over the gateway surface.
