---
tags:
  - '#adr'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:4f7adb7074a429475e856ab820f1a6e3f6d7df30d1bd7ba25f6ae74485ac4c06'
related:
  - "[[2026-10-04-a2a-edge-conformance-authoring-retry-audit]]"
  - "[[2026-10-04-engine-discovery-security-adr]]"
  - "[[2026-10-04-authoring-retry-followups-journal-retirement-adr]]"
---

# `authoring-retry-followups` adr: `Worker-owned authoring replay and isolated refresh` | (**status:** `accepted`)

## Problem Statement

The shared credential-free replay directory is writable by isolated provider descendants, so they can erase retained identity and closed markers. Those descendants cannot read protected engine discovery, so direct stdio bearer refresh fails on that profile. These concrete gaps are recorded in `2026-10-04-a2a-edge-conformance-authoring-retry-audit`.

## Considerations

The worker already owns active per-run actor credentials and catalog snapshots, drops them at run end, serves an internal HTTP listener, and reaches authenticated loopback engine endpoints. The MCP child must retain its native provider logical call identity but need not own the engine transport or replay store. Engine discovery already authenticates each TCP stream before credential disclosure.

## Considered options

- Broaden access to private discovery or keep credentials in shared files: rejected; violates credential isolation.
- Return rotated engine credentials to the child while keeping its shared journal: rejected; leaves replay integrity exposed.
- Execute bridge calls through a worker-owned runtime relay and private journal: chosen. The worker retains engine credentials and durable replay ownership; the child carries only its role's existing runtime actor credential and native logical identity.

## Constraints

Accepted under the user's 2026-10-04 instruction to continue implementing native proof, isolated refresh and shared-journal integrity follow-ups. No dashboard engine endpoint changes. The relay uses the existing worker listener, is loopback-only, accepts only a currently held run/role actor credential, and rechecks that authority after waiting for a role lock. Its proof binds a fresh challenge to the listener lifecycle and exact run/role proof path on the same connection before any actor credential is transmitted. A different role, unknown run, retired runtime token, or missing catalog cannot execute. No machine bearer, private discovery location or journal path is handed to the provider child.

The parent reads protected discovery and owns engine bearer refresh, lifecycle injection, catalog command selection and stable call journals. Private replay state retains the existing versioned owner and call identity format and the accepted deletion policy. Never import an untrusted shared journal or silently recreate an active run's identity: a run with old shared replay state and no established private journal refuses mutation and must close through the existing lifecycle before a new run begins. New state is not shared with agent UID/GID. Isolation claims apply to the separate provider OS identity; same-OS-user desktop execution does not gain a hostile-user filesystem boundary from this relay alone.

## Implementation

Add a bounded internal worker authoring route and a same-connection run/role proof route. Reuse the existing transport proof ordering with a separate relay proof domain. The worker binds its current token/catalog stores to the relay in its lifespan. Provider binding construction advertises the relay origin; the stdio MCP child dispatches names, arguments and native logical IDs to it. The relay selects the parent catalog and private run/role journal, then uses the normal AuthoringClient and make_tool_dispatch under the existing protected resolver. Weakly held locks serialize active role calls without accumulating terminal-run entries. Direct isolated launches without a relay refuse, rather than create another shared writable journal.

Retain already-existing shared files for deletion cleanup and refuse their reuse as authority. No implicit migration of their untrusted contents is authorized. Tests use real worker HTTP listeners, MCP subprocesses, private SQLite files, protected discovery and engine nonce proof. The actual Linux launcher must demonstrate bearer rotation, equal lost-response envelopes after child/relay reconstruction, and agent refusal to read or erase private replay state.

## Rationale

The existing worker runtime already has the least authority needed to reach the engine. Moving replay and refresh there removes both exposed dependencies without passing service credentials to provider descendants or adding a second listener lifecycle.

## Consequences

Worker restarts still require re-provisioned active runtime credentials; private journals preserve replay identity. Existing active shared-journal runs refuse instead of inventing a migration. The worker listener becomes an internal authoring dependency and its run/role proof must survive reconnect and port takeover tests. Engine mutation semantics and native provider capability admission remain unchanged until their separate real-turn proofs pass. This refines placement, not the accepted retention boundary. The retirement ADR's shared-placement wording is reconciled in a dated amendment preserving its earlier implementation history.
