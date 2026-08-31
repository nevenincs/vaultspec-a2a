---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:441661832d31dc535cd459424ef166fbb028fadb4e8998b713d7e26a38896a0d'
step_id: 'S07'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F1 correction half IN FLIGHT with agent contract-audit - correct the stale streaming route and the false claim that legacy api routes remain

## Scope

- `docs/a2a-edge-conformance-verb-mapping.md`

## Description

- Retire the stale legacy-route column from the edge-conformance mapping and
  correct the streaming route it advertised.

## Outcome

Closes in full, and the shape of the fix is the finding. The author confirmed IN
SOURCE FIRST that no legacy route exists - the application mounts the admin,
gateway and internal routers only - which established that the "staged
retirement" the document described had already completed.

That check changed the remedy. The honest fix was to RETIRE THE COLUMN, not to
correct a URL: a document describing a transitional state that had already ended
misleads even when its individual URLs are right. The streaming route was
corrected to the versioned run-stream path, the one surviving legacy reference
is explicitly marked retired, the section was retitled to state the retirement
is complete, and the note that the project name is a label rather than a
protocol claim was added near the top of the document.

VERIFIED AGAINST COMMITTED BLOBS rather than the working tree, which in a
shared multi-writer tree is the only check that means anything.

## Notes

This closes the correction half of its finding. The client-guide half of that
finding is separate work, deliberately gated behind the canonicalization rather
than written alongside - a guide written earlier would have documented
workarounds or described intent the interface does not deliver.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
