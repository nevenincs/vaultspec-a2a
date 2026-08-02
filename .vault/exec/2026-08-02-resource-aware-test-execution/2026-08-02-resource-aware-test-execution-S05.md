---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9c7378c7dd0f5a4e869da27d905bfab918658ebe707ac38532458dbed4e2daf0'
step_id: 'S05'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Implement registry-backed gateway and worker endpoint resolution

## Scope

- `src/vaultspec_a2a/testing/endpoints.py`

## Description

- Implement `resolve_service`, `resolve_gateway_url`, and `resolve_worker_url` in `src/vaultspec_a2a/testing/endpoints.py`: explicit env override first, else the registry's LIVE records freshest-first, each confirmed with a real health probe before trust.

## Outcome

Committed as eda3cd17. A stale-heartbeat record is refused even while its port answers; an unanswering fresh record is passed over for a healthy sibling.

## Notes

The env override is returned unprobed by design: an unreachable operator override should fail loudly downstream, not dissolve into a registry fallback.
