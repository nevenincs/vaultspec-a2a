---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S10'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Route the service discovery writer through the shared helper

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Replace the inline temporary-write and rename in the service discovery
  publication with a call to the shared helper.
- Keep every check that precedes the write untouched: the private parent
  directory, the Windows access-control assertion, and the credential handling.

## Outcome

The publication now routes through the audited helper. This is the writer that produced
the observed orphan: a temporary file bearing a process id sat beside the live discovery
record for six days, left by a publication that never completed. That failure mode is
closed, and the record additionally gains the durability flush it previously lacked.

Three lines of inline publication became one call, and the surrounding validation is
unchanged.

## Notes

The discovery record is not written with an explicit permission mode, unlike its desktop
counterpart. That matches the previous behaviour rather than extending it: the record
carries no secret, the credential lives in a separate owner-restricted file, and the
parent directory is already private. Tightening it here would have been an unrequested
behaviour change in a Step scoped to routing.
