---
tags:
  - '#exec'
  - '#tool-permission-model'
date: '2026-10-01'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:a01fb733d0f1193605d006d2f1de73eb6cce086e0a30fe3189b2447146001d8e'
related:
  - "[[2026-10-01-tool-permission-model-plan]]"
---

# `tool-permission-model` ledger

## Changes

- `S06` `M` `.vault/plan/2026-10-01-tool-permission-model-plan.md`
- `S19` `M` `.vault/plan/2026-10-01-tool-permission-model-plan.md`

## Notes

- `S06` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: C10 (R4-F11) already merged `providers/_tool_policy.py` decide() on refactor/centralize@00b50130; this Step now builds the grant model on that module
- `S08` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: C10 (R4-F11) already centralized the ACP rung's policy.decide call@00b50130; this Step adds the grant-model consultation only
- `S09` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: C10 (R4-F11) already routed Codex through policy.decide@00b50130; this Step adds the `enabled_tools` renderer and grant-model consultation only
- `S16` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: dropped the `append_permission_log` move (S.1/W05.P13.S68 does it) and added the D18 single-decision-record rule
- `S19` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: scope corrected from the stale graph/nodes/worker.py to `graph/nodes/_worker_permissions.py` (R4-F27) and consumes C.3's `graph/acp_options` kind predicates (R4-F7)
- `S15` plan-text fix per 2026-10-06-codebase-remediation-plan absorption table (R4-F27): replaced the `VAULTSPEC_A2A_TEST_POSTGRES_URL` Verification lines (D1/2026-10-07-codebase-remediation-sqlite-only-adr retires Postgres), added the migration-0026 rebase note (S.1), and recorded the C10/S.1 start gating in the Description
