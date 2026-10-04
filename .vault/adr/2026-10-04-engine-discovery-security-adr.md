---
tags:
  - '#adr'
  - '#engine-discovery-security'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:40690cb9c693beadf838dc623b3ee7bd5d46b9c93d1a2f8a314c2cc60ea5ab55'
related:
  - "[[2026-10-04-engine-discovery-security-audit]]"
  - "[[2026-09-23-project-bound-state-adr]]"
---

# `engine-discovery-security` adr: `Authenticated engine discovery outside workspaces` | (**status:** `accepted`)

Accepted 2026-10-04 under the user's instruction to fix the supplied finding. The owner extended producer authority with “Yes, fix both repositories.”

## Problem Statement

Repository-authored discovery incorrectly selects credential-bearing authoring destinations. The exploit and coordinated producer work are recorded in `2026-10-04-engine-discovery-security-audit`.

## Considerations

Generic legacy parsing also serves gateway lifecycle classification and retains that behavior. The engine trust boundary includes initial attachment and machine-bearer re-resolution. Loopback health and self-asserted PIDs do not authenticate a producer.

## Considered options

- Retain workspace discovery and match health or PID: rejected because repository authors can supply matching values.
- Private discovery outside repositories plus versioned producer identity and fresh proof of possession: chosen; old producers fail closed.
- TLS or a new local IPC transport: deferred because either requires a larger coordinated transport migration.

## Constraints

This refines D5 of `2026-09-23-project-bound-state-adr`; A2A-owned storage remains project-bound. Engine discovery reads move to protected external state. Disposable private OS temporary discovery directories are a scoped D6 test exception because this trusted state must be outside repositories. Tests and logs retain no credentials.

## Implementation

Resolution accepts only an owner-restricted regular file in a real private directory outside known workspace roots and repository ancestors. Ancestor links are refused, opened-file identity is checked, and reads are bounded. Records require integer version 1, producer `vaultspec-engine`, a valid loopback port, positive process/lifecycle identity, fresh heartbeat, and a bearer. A fresh random health challenge uses HMAC-SHA256 over producer version, port, PID, lifecycle start, and challenge. Probes disclose neither credential, disable environment proxies, and refuse redirects. Legacy/desktop generic parsing cannot authorize engine attachment. Default engine records are external per-project state; explicit overrides receive the same checks.

Review refinement, 2026-10-04: initial health proof is insufficient for a cached endpoint. HTTPX authenticates each newly opened TCP stream before writing authoring headers, consumes a bounded persistent HTTP/1.1 health response on that stream, and verifies its fresh lifecycle-bound proof. The producer returns actual PID and lifecycle start with the proof. Reused streams retain their authenticated peer; reconnects repeat the proof. HTTPcore 1.0.9 is pinned because its documented connection trace contract enforces this ordering. Bearer rotation can re-resolve once after a proof failure as well as after an outer 401.

## Rationale

Protected provenance prevents repository content from choosing the proof key. The fresh challenge proves the listener holds that key without exposing it to a listener occupying a stale port. Both checks are necessary.

## Consequences

Old producer generations are refused. Dashboard publishes matching external private records and authenticates the challenge. Seated engines keep machine seat discovery and also publish the per-project authoring rendezvous; exempt serves publish external state only. Owned gateway launches receive the exact external record path.
