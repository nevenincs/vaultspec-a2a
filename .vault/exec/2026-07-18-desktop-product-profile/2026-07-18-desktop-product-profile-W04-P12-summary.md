---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W04.P12` summary

Phase P12 delivered two-stage run admission under the existing run-start
verb and authenticated terminal settlement, admitting runs only after
execution readiness. All nine Steps (S63 through S71) are closed with an
independent review PASS carrying no critical or high findings, and the phase
also closed the containment phase's admission-leak finding. With P10, P11,
and P12 complete, Wave W04 — process and run ownership — is done.

- Modified: `src/vaultspec_a2a/api/schemas/gateway.py`,
  `src/vaultspec_a2a/api/routes/gateway.py`,
  `src/vaultspec_a2a/control/run_start_policy.py`,
  `src/vaultspec_a2a/control/event_handlers.py`
- Created: `src/vaultspec_a2a/control/admission.py`,
  `src/vaultspec_a2a/desktop/settlement.py`,
  `src/vaultspec_a2a/desktop_tests/test_run_admission.py`,
  `src/vaultspec_a2a/desktop_tests/test_terminal_settlement.py`,
  `src/vaultspec_a2a/desktop_tests/test_standalone_mcp.py`

## Description

The admission broker holds hard-bounded, expiring prepare reservations:
capacity checks and inserts are atomic, expiry sweeps and commits share one
lock so an expired reservation can never commit, and failed commits release
their reservation. Prepare validates required roles, capacity, single-flight
worker startup, and provider eligibility while remaining side-effect-free —
the schema itself rejects actor tokens at prepare, and no durable run or
run-owned child exists before commit. The stage dispatcher rides the
existing run-start verb with the route table unchanged; commit binds
dashboard-minted actor tokens to a stable run and a non-secret lease
persisted for restart reconciliation, gated on worker and provider
eligibility evaluated before any token is accepted. Terminal settlement
emits bounded callbacks authenticated with the dashboard-created attach
credential, carrying run and lease identities only, triggered idempotently
after execution-state persistence with an honest at-most-once contract
backstopped by status reconciliation. The folded remediation made the
run-creation core release its drain-gate admission on every non-durable
failure, proven by a mock-free forced database failure. Certifications run
against real armed gateways: concurrent prepares respect the bound and
create one worker, timeouts and failed commits leak nothing, the settlement
receiver rejects worker IPC and unrelated credentials, and a clean installed
capsule starts and stops the standalone adapter under caller ownership with
the desktop lifecycle uninvolved.

## Tests

Five hundred nineteen tests across the api, control, and worker suites, the
four admission and settlement certifications, and the two installed-capsule
standalone-adapter gates are green with real child processes, real sockets,
real credential files, and no fakes, mocks, stubs, patches, monkeypatches,
skips, or expected failures. Review confirmed every admission and settlement
invariant from the decision record with two optional low notes accepted
as-is (a settlement retry nicety and an established private health-probe
reach-in).
