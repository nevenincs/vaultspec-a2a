---
tags:
  - '#reference'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d739ecd150ef8d28f2608c519adcd97cbe4e8c3d7db98055d86482ed3213400b'
related:
  - "[[2026-08-02-control-action-leases-research]]"
---

# `control-action-leases` reference: `existing control journal and resume paths`

This reference maps the shared durable journal, affected dispatch callers, worker
admission boundary, and checkpoint surfaces needed for application reconciliation.

## Summary

`ControlActionModel` in `src/vaultspec_a2a/database/models.py:265` is the canonical
orchestration journal. Its unique thread and idempotency-key constraint is consumed
through `get_or_create_control_action` in
`src/vaultspec_a2a/database/permission_repository.py:247`; lease reservation should
extend this owner rather than introduce caller-local locking.

The primitive needs persisted `dispatch_id`, `claim_token`, and `claim_expires_at`
fields, plus conditional acquire, release, replay/conflict, and applied-settlement
operations. Migration and lifecycle coverage belong to the existing database owners.

Clarification orchestration currently lives inline in
`src/vaultspec_a2a/api/routes/gateway.py:1918`. A new
`src/vaultspec_a2a/control/clarification_service.py` should own typed payload
fingerprinting, checkpoint validation, reservation, pre-dispatch commit, stable-ID
dispatch, replay/conflict mapping, and reconciliation. The route remains an adapter.

Permission at `src/vaultspec_a2a/control/permission_service.py:311`, follow-up
messages at `src/vaultspec_a2a/control/message_service.py:58`, cancellation at
`src/vaultspec_a2a/control/cancel_service.py:136`, and verdict resume at
`src/vaultspec_a2a/control/verdict_subscriber.py:640` are the remaining callers.

The worker endpoint at `src/vaultspec_a2a/worker/app.py:222` acknowledges scheduling,
not execution. Recovery attempts reuse the persisted dispatch ID; the worker must
synchronously suppress a repeated ID before scheduling it, with bounded retention.

The clarification gate at
`src/vaultspec_a2a/graph/nodes/clarification.py:332` should emit a request-id and
payload-fingerprint receipt in `TeamState`. The receipt, not worker HTTP success or
transcript inference, settles the journal action as applied.

Deterministic proofs extend
`src/vaultspec_a2a/api/tests/test_clarification_loop_live.py:64`. The provider proof
belongs beside `src/vaultspec_a2a/service_tests/test_clarification_loop_stitched.py`
and freezes active roles onto low Codex before starting the run.
