---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:366ee76c3541bd9394deb26eadd6a76b4aa02fe44170978b14a6c7d88d38f7ef'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# `control-action-leases` ledger

## Changes

- `S01` `T` `src/vaultspec_a2a/database/models.py`
- `S01` `T` `src/vaultspec_a2a/database/migrations/versions/0012_control_action_leases.py`
- `S02` `T` `src/vaultspec_a2a/database/permission_repository.py`
- `S02` `T` `src/vaultspec_a2a/database/__init__.py`
- `S03` `T` `src/vaultspec_a2a/database/tests`
- `S04` `T` `src/vaultspec_a2a/worker/app.py`
- `S04` `T` `src/vaultspec_a2a/worker/dispatch_ids.py`
- `S05` `T` `src/vaultspec_a2a/worker/tests`
- `S06` `T` `src/vaultspec_a2a/thread`
- `S06` `T` `src/vaultspec_a2a/graph/nodes/clarification.py`
- `S07` `T` `src/vaultspec_a2a/control/clarification_service.py`
- `S08` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S08` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S09` `T` `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `S09` `T` `src/vaultspec_a2a/database/reconciliation.py`
- `S10` `T` `src/vaultspec_a2a/control/permission_service.py`
- `S11` `T` `src/vaultspec_a2a/control/event_handlers.py`
- `S12` `T` `src/vaultspec_a2a/control/message_service.py`
- `S13` `T` `src/vaultspec_a2a/control/cancel_service.py`
- `S14` `T` `src/vaultspec_a2a/control/verdict_subscriber.py`
- `S15` `T` `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`
- `S16` `T` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S17` `T` `src/vaultspec_a2a/api/tests`
- `S17` `T` `src/vaultspec_a2a/lifecycle/tests`
- `S18` `T` `src/vaultspec_a2a/control/tests`
- `S18` `T` `src/vaultspec_a2a/api/tests`
- `S19` `T` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S20` `T` `src/vaultspec_a2a/service_tests/test_clarification_loop_stitched.py`
- `S20` `T` `config/model_profiles.toml`
- `S21` `T` `src/vaultspec_a2a/service_tests`
- `S21` `T` `src/vaultspec_a2a`
- `S22` `T` `.vault/audit`
