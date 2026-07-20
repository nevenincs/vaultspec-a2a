---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S104'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Make prepared commit and release crash-recoverable under one stable run identity with a pre-minted lease, a recoverable committing transition, durable exact replay, backward-compatible status, and real failure, restart, race, and lost-ack proofs

## Scope

- `src/vaultspec_a2a/control/admission.py`
- `src/vaultspec_a2a/api/body_limit.py`
- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/tests/test_app.py`
- `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- `src/vaultspec_a2a/database/migrations/__init__.py`
- `src/vaultspec_a2a/database/tests/test_checkpoint_state_migration.py`
- `src/vaultspec_a2a/desktop_tests/test_run_admission.py`
- `src/vaultspec_a2a/desktop_tests/test_terminal_settlement.py`
- `src/vaultspec_a2a/thread/actor_tokens.py`
- `src/vaultspec_a2a/thread/tests/test_actor_tokens.py`
- `src/vaultspec_a2a/utils/process.py`
- `src/vaultspec_a2a/worker/app.py`
- `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `src/vaultspec_a2a/worker/tests/test_executor.py`
- `src/vaultspec_a2a/service_tests/_live_desktop_gateway.py`
- `src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py`

## Description

- Require one stable run identity across prepare, commit, and release.
- Mint the non-secret lease at prepare and bind the prepared request plus exact role set.
- Retain reservations in a recoverable committing state until the exact run binding is durable.
- Roll back failed request transactions before classifying durable state and restoring authority.
- Recover exact acknowledgements and lease status from persisted metadata across gateway restart.
- Preserve the preceding lease-only status shape and reject altered replays.
- Bound and strictly validate v1 bodies, actor-token fields, role keys, and secret sizes.
- Materialize restart-required SDD channels while recognizing LangGraph input-staging rows.
- Prove failure, release/commit races, restart, lost acknowledgement, bounded input, and worker dispatch with real processes and stores.

## Outcome

Status: IMPLEMENTED; FINAL FORMAL RE-REVIEW PENDING.

The staged admission path no longer deletes its only reservation authority before
durability. Exact durable replay returns the same run and lease without redispatch,
while a real post-authorization nickname conflict restores the original reservation
for a binding-matched release. A new gateway process recovers the same persisted
lease, and the live dashboard-engine relay demonstrates one accepted dispatch after
an intentionally dropped acknowledgement without retaining credential-bearing bodies.

Current verification passes 86 changed-surface tests, the independent real dashboard
service proof, Ruff, Ty, six documentation tests, and nitpicky Sphinx with warnings as
errors. The repository-wide CI snapshot passed 2,572 tests before the final strict-wire
and transaction-classification edits; it must be rerun on the final frozen bytes.

## Notes

No data was removed. The live RAG process was not killed; CI uses an isolated virtual
environment to avoid its legitimate executable lock. S101 remains independently open
for the unproved 512-descriptor and 8 GiB supported-target retention envelope.
