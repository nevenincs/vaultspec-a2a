---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:511bb34e9dffc440392b7f8b8dc9e93f792394e93177e69002224bd7f0ad20f1'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# `served-capability-contract` ledger

## Changes

- `S01` `T` `src/vaultspec_a2a/providers/_codex_config_home.py`
- `S02` `T` `src/vaultspec_a2a/streaming/ingest.py`
- `S03` `T` `src/vaultspec_a2a/authoring/submitter.py`
- `S04` `T` `src/vaultspec_a2a/control/run_start_policy.py`
- `S07` `T` `docs/a2a-edge-conformance-verb-mapping.md`
- `S08` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S09` `T` `src/vaultspec_a2a/api/app.py`
- `S12` `T` `src/vaultspec_a2a/api/schemas/snapshots.py`
- `S16` `T` `docs/development.rst`
- `S17` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S18` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S19` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S21` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S23` `T` `src/vaultspec_a2a/streaming/transformer.py`
- `S23` `T` `src/vaultspec_a2a/streaming/emitters.py`
- `S23` `T` `src/vaultspec_a2a/control/snapshot.py`
- `S25` `T` `src/vaultspec_a2a/control/run_discovery_service.py`
- `S35` `T` `src/vaultspec_a2a/authoring/session.py`
- `S27` `M` `src/vaultspec_a2a/api/routes/gateway.py`
- `S30` `M` `src/vaultspec_a2a/api/routes/gateway.py`
- `S44` `M` `src/vaultspec_a2a/api/routes/gateway.py`

## Notes

- `S27` absorbed by 2026-10-06-codebase-remediation-plan: PV08 (R1-F8a) generates the stream response class and catalog-generated frame schema, unpublishes /internal and types /health@818e4f56,09db6002,343749d3 on refactor/centralize. Residual caveat: S27's own text also named F19 sequence recovery and closing ER06 (subscriber-before-snapshot attachment); those are not evidenced by the PV08 commits and are flagged to the orchestrator for separate verification
- `S30` absorbed by 2026-10-06-codebase-remediation-plan: PV03 (R5-F1) makes served eligibility completed-turn proof + an admitted binary@f8c906fc, and L06 shares one configured-state probe between readiness and catalog discovery@f5c24be8 on refactor/centralize, reconciling `eligible_providers` with the catalog admission predicate
- `S44` absorbed by 2026-10-06-codebase-remediation-plan: PV03 (R5-F18) defines the run-start eligible boolean strictly as the proven admitted-binary outcome@f8c906fc on refactor/centralize
- `S04` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: keep only the F16/F67 predicate work; the authoring-preset predicate (R2-F15) is owned by M06@01fa7073
- `S29` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: after D2, classification serves source-run serving only
- `S57` re-scoped per 2026-10-06-codebase-remediation-plan absorption table: after D2, classification and re-key serve source-run serving only
