---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2c757bf01ad3b2ae9c4c38fa3c67ddd209381ed7811d1fec6408b85128343a36'
step_id: 'S20'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Tighten the proofs against fallback passes and isolated-home binds

## Scope

- `src/vaultspec_a2a/testing/tests/`

## Description

- Assert the reservation path ran inside the cross-process proof (in-band
ports), reserve the bindable-port proof in the real machine-global home,
correct the scheduling-evidence attribution prose, and prove heartbeated
holds past the TTL.

## Outcome

Committed as 1bff981f (with S17's guard).

## Notes

None.
