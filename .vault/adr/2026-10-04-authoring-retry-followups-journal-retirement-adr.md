---
tags:
  - '#adr'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:742c99232002975c0d3c7a326192c1e827d4cd73beb7fa9233e7cc5fbbb473ef'
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

Final review refinement on 2026-10-04: construct the small closed SQLite header in memory using the journal's shared schema definitions, and write through the originally created exclusive descriptor. Flush and verify named/descriptor identity before atomic replacement. Do not reopen the temporary shared pathname for writes. Candidate SQLite inspection is read-only; closed POSIX headers grant the agent group read access without write access. S03 was reopened for the temporary-path finding and closed after its correction, repeat retirement/deletion checks and the actual Linux identity proof passed. Hostile mutation of the shared directory itself remains a separate audited authority gap; these checks establish the cooperative bridge lifecycle boundary.

Placement refinement, 2026-10-04, authorized by the user's instruction to continue the remaining follow-ups: `2026-10-04-authoring-retry-followups-parent-authority-adr` moves production provider replay authority to the worker's private journal directory and executes child calls through its runtime relay. The earlier shared-directory implementation above remains historical; new isolated launches do not provision or reuse shared journals. Existing shared files remain eligible for explicit deletion cleanup, while an active legacy run without an established private journal refuses mutation rather than importing untrusted identity. Retention, marker lifetime, closed owner version and durable deletion outcomes are unchanged.

Run-index refinement, 2026-10-04, authorized by the user's instruction to eliminate the remaining degraded cleanup: the run-index ADR replaces repeated flat scans with a service-private store/run/role index. Historical owner/filename inspection occurs once when adopting an unindexed store. Thereafter index ownership authorizes compact closed replacement even if the indexed SQLite payload is corrupt. Closure is durable before replacement; the source contents are never used to recreate active identity. Unclassifiable or foreign historical files are preserved and do not fail another run's cleanup. Index rows are removed only after successful compaction. The earlier per-delete scan and source-owner-read implementation above remains history; retention, closed marker lifetime, stable paths and saga outcomes are unchanged.

## Rationale

Explicit deletion is the existing irreversible history boundary; terminal settlement alone is not. A retained close marker is necessary because an absent file does not prove that a logical call was previously executed. The marker closes replay without retaining individual call data.

## Consequences

Call data is reclaimed on explicit deletion, while a small closed marker and owner database remain. Retained terminal runs continue to consume their replay history. Discovery of owned flat journals costs a directory scan per delete; a run index may be needed at larger scale. Reconsider the policy if run IDs can be reused or a new contract permits reviving deleted runs; neither is allowed now.
