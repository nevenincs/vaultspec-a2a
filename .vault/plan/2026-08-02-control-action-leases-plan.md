---
tags:
  - '#plan'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:61e765706a8e258e411f5b169bc143d619380c5e85fe3303fd82501106a01928'
tier: L3
related:
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-08-02-control-action-leases-research]]'
  - '[[2026-08-02-control-action-leases-reference]]'
---

# `control-action-leases` plan

## Steps

## Wave `W01` - establish durable dispatch ownership

Build the shared database and worker primitives that every later migration depends on.

### Phase `W01.P01` - persist atomic lease state

Extend the control journal and repository with one cross-process reservation and lease contract.

- [x] `W01.P01.S01` - Add generic dispatch lease fields and migration; `src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/database/migrations/versions/0012_control_action_leases.py`.
- [x] `W01.P01.S02` - Implement atomic reserve acquire release and settle operations; `src/vaultspec_a2a/database/permission_repository.py, src/vaultspec_a2a/database/__init__.py`.
- [x] `W01.P01.S03` - Prove concurrent lease elections and migration lifecycle completeness; `src/vaultspec_a2a/database/tests`.

### Phase `W01.P02` - suppress duplicate worker dispatch

Make stable dispatch identity effective at the asynchronous worker admission boundary.

- [x] `W01.P02.S04` - Add bounded synchronous dispatch id admission; `src/vaultspec_a2a/worker/app.py, src/vaultspec_a2a/worker/dispatch_ids.py`.
- [x] `W01.P02.S05` - Prove duplicate dispatch ids schedule one executor task; `src/vaultspec_a2a/worker/tests`.

## Wave `W02` - harden parked resume paths

Move clarification and permission resumption onto committed leases with authoritative application evidence.

### Phase `W02.P03` - journal clarification resolution

Give clarification one typed service, deterministic replay semantics, and checkpoint application receipts.

- [x] `W02.P03.S06` - Add clarification resolution receipts to domain and graph state; `src/vaultspec_a2a/thread, src/vaultspec_a2a/graph/nodes/clarification.py`.
- [x] `W02.P03.S07` - Implement leased clarification orchestration service; `src/vaultspec_a2a/control/clarification_service.py`.
- [x] `W02.P03.S08` - Reduce clarification route to the leased service adapter; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/schemas/gateway.py`.
- [x] `W02.P03.S09` - Reconcile parked and applied clarification leases after restart; `src/vaultspec_a2a/lifecycle/reconciliation.py, src/vaultspec_a2a/database/reconciliation.py`.

### Phase `W02.P04` - journal permission resolution

Close the equivalent permission race without changing permission semantics.

- [x] `W02.P04.S10` - Migrate permission response reservation and dispatch to shared leases; `src/vaultspec_a2a/control/permission_service.py`.
- [x] `W02.P04.S11` - Settle permission leases from authoritative progress events; `src/vaultspec_a2a/control/event_handlers.py`.

## Wave `W03` - harden remaining control paths

Remove lookup-before-dispatch and metadata-claim races from every remaining caller found by the audit.

### Phase `W03.P05` - lease direct gateway controls

Apply the common election to follow-up messages and cancellations.

- [x] `W03.P05.S12` - Migrate follow-up message dispatch to shared leases; `src/vaultspec_a2a/control/message_service.py`.
- [x] `W03.P05.S13` - Migrate cancellation dispatch to shared leases; `src/vaultspec_a2a/control/cancel_service.py`.

### Phase `W03.P06` - lease verdict subscriber resumes

Replace whole-metadata claims with the database election while preserving stale redrive behavior.

- [x] `W03.P06.S14` - Migrate verdict resume ownership to shared leases; `src/vaultspec_a2a/control/verdict_subscriber.py`.
- [x] `W03.P06.S15` - Remove obsolete metadata claim helpers and ratchet single ownership; `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`.

## Wave `W04` - prove recovery and live execution

Establish deterministic concurrency and crash recovery first, then certify the composed path under real low-cost provider load and formal review.

### Phase `W04.P07` - prove deterministic control integrity

Exercise production stores transports worker and graph without mocks or mirrored logic.

- [x] `W04.P07.S16` - Prove identical and competing concurrent clarification submissions; `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`.
- [x] `W04.P07.S17` - Prove lost acknowledgement expired lease and restart redrive; `src/vaultspec_a2a/api/tests, src/vaultspec_a2a/lifecycle/tests`.
- [x] `W04.P07.S18` - Prove permission message cancel and verdict race safety; `src/vaultspec_a2a/control/tests, src/vaultspec_a2a/api/tests`.
- [x] `W04.P07.S19` - Replace the clarification negative recording stub with real boundaries; `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`.

### Phase `W04.P08` - certify live provider load and review

Run a real all-low Codex continuation load and close every formal review finding.

- [x] `W04.P08.S20` - Add an all-low Codex clarification load certification; `src/vaultspec_a2a/service_tests/test_clarification_loop_stitched.py, config/model_profiles.toml`.
- [x] `W04.P08.S21` - Run live Codex load and focused repository quality gates; `src/vaultspec_a2a/service_tests, src/vaultspec_a2a`.
- [x] `W04.P08.S22` - Audit the complete implementation and queue or fix every finding; `.vault/audit`.
