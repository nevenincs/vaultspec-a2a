---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:0ab6182a4f93879723910a56471346733b059aed88d6954e2328a81574ef75ca'
step_id: 'S18'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F23 shape one - serve the TopologyType enumeration that already exists in code instead of a bare string, and reconcile provider_id with the typed Provider enumeration served beside it

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Serve the enumerations that already existed in code but were discarded at the
  wire, and declare owning types for the vocabularies that had none.

## Outcome

Closes in full, as part of the vocabulary wave landed across two commits. Ten of
the eleven captured vocabularies were declared and are now served as their
owning enumerations.

The artifact was regenerated and then SEMANTICALLY DIFFED rather than trusted
for being green, and the reason is specific to this tree: the artifact generates
from the LIVE APPLICATION, so a dirty working tree can silently bake another
agent's uncommitted routes into a published contract. The diff confirmed seven
schemas added, seven models changed, and ZERO PATHS ADDED OR REMOVED - the last
being the assertion that matters, since a path appearing would have meant
exactly that contamination.

## Notes

Four of the vocabularies declared here were originally misfiled in this
feature's audit as having no owning type at all. They had one; it was being
discarded at the boundary. The correction moved them from a design task to an
annotation, and it is recorded in the audit because it changed the cost estimate
for this Wave rather than only its wording.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
