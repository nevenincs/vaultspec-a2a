---
tags:
  - '#adr'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:f5ae735d45a4af1b74953a318ebaeb6b38172b45ab675a5fc65972926be39002'
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

Use a deterministic credential-free marker in each configured authoring journal directory. Capture each existing store root as an immutable authoring-replay cleanup item using the existing artifact_file kind. The deletion saga independently executes and records those items, releases its claim after incomplete passes, and preserves its existing three-attempt abandonment/reporting policy. An abandoned item retains its replay data; failure never permits eviction or fresh identity.

Close the run and durably flush its marker before reclaiming rows. Verify each candidate's run/scope owner and deterministic filename, then atomically replace its owned database with a compact empty closed owner header. This also permits retirement of legacy agent-owned files that the service can read but cannot write. New isolated journal files are created by the service with explicit group read/write access before handing them to the agent. Existing linked or multiply-linked candidates are refused or skipped, and foreign run data is left alone. The run marker fences new role paths; unsupported owner version 2 fences existing paths for earlier bridge binaries. Keep source-version handling explicit, without translating unsupported ownership.

Implementation review on 2026-10-04 replaced an initial coordinator hook with manifest-driven cleanup because a hook failure could retain the deletion claim and bypass bounded abandonment. The accepted retention and closed-identity constraints are unchanged.

## Rationale

Explicit deletion is the existing irreversible history boundary; terminal settlement alone is not. A retained close marker is necessary because an absent file does not prove that a logical call was previously executed. The marker closes replay without retaining individual call data.

## Consequences

Call data is reclaimed on explicit deletion, while a small closed marker and owner database remain. Retained terminal runs continue to consume their replay history. Discovery of owned flat journals costs a directory scan per delete; a run index may be needed at larger scale. Reconsider the policy if run IDs can be reused or a new contract permits reviving deleted runs; neither is allowed now.
