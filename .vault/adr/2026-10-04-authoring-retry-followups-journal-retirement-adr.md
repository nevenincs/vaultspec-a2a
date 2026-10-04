---
tags:
  - '#adr'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:53d3ddd05bcf08c3a1c3218d76515b1d613dd6d2f3c424df4a7936b39685a875'
related:
  - "[[2026-10-04-a2a-edge-conformance-authoring-retry-audit]]"
  - "[[2026-10-01-run-continuation-adr]]"
---

# `authoring-retry-followups` adr: `Retain replay identity until durable run deletion, then close and compact` | (**status:** `accepted`)

## Problem Statement

Completed and ambiguous authoring call records grow without a reclamation boundary. Removing a record while a bridge can replay its logical call would recreate the security finding recorded in `2026-10-04-a2a-edge-conformance-authoring-retry-audit`.

## Considerations

The run-continuation decision forbids reopening a settled run and gives continuation a new run ID. The deletion coordinator first durably elects DELETING and rejects further control dispatch, then performs external cleanup before finalizing control-row removal. An old bridge may nevertheless reconnect using its already-issued path and identity.

## Considered options

- Age or count eviction during a retained run saves space but destroys replay identity; rejected.
- Delete journal files at terminal settlement saves space but lets stale processes recreate an empty journal; rejected.
- Keep call records until explicit durable deletion, then retain a closed run marker and compact owned journals; chosen. It preserves replay while history exists and prevents identity recreation after cleanup.

## Constraints

Accepted under the user's 2026-10-04 instruction to continue the journal-retention follow-up. Keep all pending, rejected and completed calls while the run is retained, including terminal history. After the durable DELETING election, close the run before removing journal rows. Every journal transaction checks that marker; new roles and reconstructed dispatchers refuse. Mark closed existing journals with an unsupported owner version so already-running earlier bridge code also refuses their reuse. Keep the run marker for the lifetime of the state installation; ordinary time/count sweeps must not remove it. Cleanup never touches another run's rows or follows linked journal files. No document body or credential is added to the journal.

This is a separate store-retention refinement within the authoring-edge and action-lease constraints. It changes no engine endpoint or public cleanup-kind vocabulary and does not reverse the run-continuation decision. No older accepted ruling requires replacement.

## Implementation

Use a deterministic credential-free marker in each configured authoring journal directory. The deletion coordinator closes and compacts matching owned SQLite journals before finalizing its existing deletion saga. A failure retains DELETING and reports incomplete cleanup for retry. Existing cleanup items keep their own independent outcomes. A completed retirement deletes per-call/lifecycle rows and vacuums the owned database, retaining its closed owner header. The marker also fences any new journal path for that run. Keep source-version handling explicit, with no translation of unsupported ownership.

## Rationale

Explicit deletion is the existing irreversible history boundary; terminal settlement alone is not. A retained close marker is necessary because an absent file does not prove that a logical call was previously executed. The marker closes replay without retaining individual call data.

## Consequences

Call data is reclaimed on explicit deletion, while a small closed marker and owner database remain. Retained terminal runs continue to consume their replay history. Discovery of owned flat journals costs a directory scan per delete; a run index may be needed at larger scale. Reconsider the policy if run IDs can be reused or a new contract permits reviving deleted runs; neither is allowed now.
