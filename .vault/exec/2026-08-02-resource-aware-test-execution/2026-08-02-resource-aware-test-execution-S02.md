---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:64437d95b77007d499f0007eb16297e895badddc3b7192fc8c79ae6a3220962d'
step_id: 'S02'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Implement the resource catalog and marker vocabulary

## Scope

- `src/vaultspec_a2a/testing/resources.py`

## Description

- Implement `ResourceSpec`, `ResourceClaim`, the cataloged vocabulary, `resolve_spec`, `declared_claims`, and `exclusive_keys` in `src/vaultspec_a2a/testing/resources.py`.
- Catalog `loopback-stack`, `compose-stack`, the three CLI lanes, and `zai-lane`, each linked to its conftest prerequisite id with an 1800s backstop; admit ad-hoc `scratch-` keys for framework validation.

## Outcome

Committed as 460dc927. Unknown keys raise naming the catalog; a key claimed both shared and exclusive collapses to exclusive.

## Notes

None.
