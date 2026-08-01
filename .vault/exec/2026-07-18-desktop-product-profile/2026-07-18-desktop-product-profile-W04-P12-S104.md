---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-30'
body_hash: 'sha256:0380cb8a1bc5db994235a07696159ed22a1a2c9d64f2acd44fdc23a859f5cbe9'
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

Status: IMPLEMENTED AND RE-CERTIFIED AGAINST HEAD, WITH ONE CONTRACT CLAUSE UNPROVEN ON TODAY'S BYTES.

The staged admission path no longer deletes its only reservation authority before
durability. Exact durable replay returns the same run and lease without redispatch,
while a real post-authorization nickname conflict restores the original reservation
for a binding-matched release. A new gateway process recovers the same persisted
lease.

The earlier sign-off was taken against 2026-07-20 bytes, and six commits have since
touched scoped files. A fresh formal review re-derived the invariants from source at
HEAD and found them intact: the admission module and the pre-parse write cap are
byte-identical to the certified version; the recoverable-committing and exact-replay
path still refuses a replay whose reservation id or commit digest differs under
constant-time comparison; the post-durability classifier still separates
authoritatively-absent from unreadable-or-conflicting; and the commit-time readiness
gate remains fail-closed after the worker-health readers were collapsed onto one
probe. One invariant was strengthened rather than weakened - a plain-start replay now
compares the whole persisted request digest instead of the profile field alone, with a
narrower fallback preserving legacy runs that carry no digest.

Touched-area verification on HEAD, run through the project virtual environment: the
combined interface, control, thread, and store packages pass 896 tests; the worker
package passes 89; the real-process desktop suite passes 43, with skip reporting
forced on and none reported. That suite executed all four of this Step's named proofs
- restart and lease recovery, exact commit replay with role binding and release-race
linearization, pre-durability commit failure restoring the reservation, and a
reservation timeout refusing its commit. No failures and no skips across the three
commands. The whole-tree type gate is NOT clean: 17 diagnostics stand, none of them in
a scoped file, 14 being unresolved imports against optional extras absent from this
environment and 3 apparent protocol-SDK drift.

The lost-acknowledgement clause of this Step's contract could NOT be re-certified. Its
proof needs a cross-repository engine binary supplied through an environment template
that is absent here, so the module skipped rather than ran. A skip is not a pass: that
clause still rests on the 2026-07-20 run and is queued as a finding. Nothing was
stubbed, faked, or substituted to close the gap. The repository-wide suite, Ruff,
deptry, and the documentation gates were likewise not re-run today, so no
repository-wide green is claimed here.

## Notes

No data was removed. The live RAG process was not killed; CI uses an isolated virtual
environment to avoid its legitimate executable lock. S101 remains independently open
for the unproved 512-descriptor and 8 GiB supported-target retention envelope.


Re-certification residue, recorded so it stays visible: the absent-engine case is now
quiet by default. The missing-prerequisite handling moved from a hard assertion inside
the command builder to the repository-wide external-prerequisite fixture, which is a
legitimate consolidation, but it means anyone re-running the lost-acknowledgement
proof must either declare the prerequisite guaranteed - turning absence into a
failure - or read the skip line. Reading a default run as green would be wrong.
