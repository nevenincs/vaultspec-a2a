---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:65d9f5e8c14da800fe7922798d48c333b1fa33f03c32761babdd621c664946b7'
step_id: 'S19'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F23 shape two - declare owning enumerations for the vocabularies that have none, covering origin, repair_status, execution_readiness, provider_condition, worker_status, semantic_status, semantic_phase, replay_status and the degraded_reasons members

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Declare owning enumerations for the served vocabularies that had none in code
  or on the wire.

## Outcome

Closes in full, landed with its sibling declaration Step across the same two
commits. The vocabularies that genuinely had no owner - as against those that
had one and discarded it - received declarations in small owning modules rather
than being appended to the two modules already over the repository's size
mandate.

That placement was deliberate and follows an existing precedent in the codebase:
new declarations went to narrow modules that own their concept, so the growth in
the large modules is annotations and documentation rather than new types.

## Notes

Neither oversized module was fixed by this Step, and that is recorded as a
finding in this feature's audit rather than silently carried. The mandate is
enforced by no gate, so a module crosses it silently and only a reader notices -
which is the same rule-without-a-mechanism shape the audit records elsewhere.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
