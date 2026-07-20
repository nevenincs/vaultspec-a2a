---
tags:
  - '#adr'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-codebase-health-research]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]"
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
  - '[[2026-07-15-dev-process-registry-adr]]'
---

# `codebase-health` adr: `failure-atomic hardening across the dashboard-owned runtime` | (**status:** `accepted`)

## Problem Statement

Accepted records define the dashboard-owned runtime, Agent-to-Agent (A2A) edge,
subprocess
ownership, and real-process evidence standard. The health audit found that
several implementations violate those records. It also exposed missing
decisions for cross-store deletion, request identity, positive progress
schemas, and shared release criteria.

This record decides those cross-cutting invariants without replacing the
existing topology. Grounding lives in `2026-07-19-codebase-health-research`.

## Considerations

- Existing desktop ownership, authentication, singleton, admission, and cleanup
  decisions remain binding (`2026-07-18-desktop-product-profile-adr`).
- The five-verb dashboard edge and its bounded, versioned transport remain
  binding (`2026-07-14-a2a-edge-conformance-adr`).
- The completed A2A plan contradicts the accepted dashboard token-stream
  decision. Plans cannot override architecture decision records (ADRs). This
  record preserves the dashboard decision; removing token streaming requires
  paired dashboard and A2A ADR amendments
  (`2026-07-19-codebase-health-research`).
- Real-process certification remains the release evidence standard
  (`2026-03-31-integration-testing-smoke-tests-api-verification-adr`).
- Repository tooling, dependency-gate configuration, workflows, and general
  documentation remain owned by
  `2026-07-19-repository-tooling-hardening-adr`.
- The audit queue and option comparison live in
  `2026-07-19-codebase-health-research`.

## Considered options

- **One invariant-level roll-up decision and plan - chosen.** Adds only the
  missing failure, identity, transport, and evidence rules. Existing records
  remain the owners of topology and profile behavior.
- **Amend every parent record.** Rejected because most required behavior is
  already stated. Repetition would create several partial hardening plans.
- **Patch each finding without a new decision.** Rejected because thread
  deletion and edge identity require choices that no accepted record owns.
- **Replace the runtime topology.** Rejected because the failures concern
  ownership enforcement, not the gateway-worker split itself.

## Constraints

- This record does not supersede or weaken any related ADR.
- The dashboard and A2A repositories remain one certification boundary. The
  dashboard continues to consume A2A only through the frozen Hypertext Transfer
  Protocol (HTTP) edge.
- Existing desktop attach, administration, and worker authentication rules are
  inherited release criteria. Only a content-free liveness probe may remain
  unauthenticated in that profile.
- Files, checkpoints, and control rows do not share a transaction manager.
  Destructive workflows must expose retryable intermediate state.
- Every subprocess, task, pipe, queue, and temporary artifact has one owner and
  a bounded lifetime.
- Verification cannot use fakes, mocks, stubs, patches, monkeypatching, skipped
  tests, or expected failures as product evidence.
- Active desktop, tooling, and observability plans retain ownership of their
  current files. Hardening work must consume or sequence after those changes.
- The service-lifecycle supersession conflict identified by
  `2026-07-19-codebase-health-research` must be curated before implementation
  relies on that decision chain.

## Implementation

### Runtime ownership and provenance

Every gateway has a lifetime instance identity. Every worker has its own
generation identity and an explicit paired gateway identity. An authenticated
readiness response proves both identities with the worker interprocess
credential. Plain health, a blank pairing field, or an unauthenticated legacy
response proves liveness only and never permits adoption. Desktop and Compose
workers follow the same provenance rule.

Only an owner-authorized desktop auto-spawn gateway may evict its prior worker.
A failed authorized eviction produces a conflict and never falls back to plain
health. Compose workers remain independently managed. Any Compose provenance
mismatch fails closed without eviction.

Runtime startup uses one transaction to reserve resources, spawn the process,
verify readiness, and commit state. Any failure after spawn terminates the
complete owned process tree before releasing the reservation. A runtime
singleton is acquired before port binding or discovery publication.

### Cross-store thread deletion

The control database coordinates deletion as a durable saga. The first
transaction marks the thread as deleting and records a bounded cleanup
manifest. Normal run and list operations no longer expose the thread as active.

An idempotent cleanup owner deletes checkpoints and artifacts, records each
result, and retries incomplete work. The final transaction removes control rows
only after every required cleanup item succeeds. Replayed requests resume the
same saga.

### Authenticated and positive edge contracts

The supported public product surface is the five versioned verbs and the
versioned progress stream. Desktop authentication remains governed by its
accepted parent ADR.

Legacy product routes and WebSockets enter a bounded deprecation period. During
that period, they require a configured attach
credential and are never advertised to the dashboard. A Compose deployment
without that credential disables those transition surfaces.

Administrative
shutdown requires the lifecycle ownership capability. Worker routes continue
to require the distinct worker credential.

The transition ends after joint certification proves that the dashboard has no
legacy dependency.

Run-start replay stores a canonical fingerprint of every behavior-affecting
request field. A matching `run_id` with a different fingerprint returns HTTP
`409 Conflict`.

The progress channel uses a versioned positive schema. It carries identifiers,
lifecycle state, bounded counters, explicitly approved summaries, and one
dedicated bounded token-delta field. It never carries prompts, document bodies,
raw provider payloads, artifact bodies, or edit diffs. Durable state remains
available through `run-status`. Removing the token-delta field requires paired
dashboard and A2A ADR amendments.

Before authentication, connection and global limits protect remaining public
probes. After authentication, per-principal limits also apply. The progress
stream requires authentication when this decision is implemented.

### Provider and resource failure containment

Configuration admission rejects duplicate server identities. Every provider
adapter continuously drains bounded standard error (`stderr`) and owns all
background protocol tasks. Handler failures produce a protocol error or
terminate the session; they cannot remain log-only events.

Turn, request, and
cleanup operations have deadlines. Cleanup steps run independently so one
failure cannot skip later credential, configuration, task, or process cleanup.

### Evidence and health-debt completion

The dashboard repository owns the release-blocking composite certification job
because it assembles and consumes the product. The A2A repository owns its
gateway-worker certification fixture and contract scenarios. The composite job
exercises the dashboard engine, A2A gateway and worker, deterministic provider
execution, the dashboard facade, authenticated streaming and reconnection,
deletion recovery, and proposal review. Static and unit gates remain separate
supporting signals.

Blocker waves precede dead-code, duplication, dependency, and complexity work.
An exported surface is removed only when no in-repository or dashboard
compatibility owner exists. Every wave ends with a formal code review and
appends new findings to the rolling audit queue.

## Rationale

The roll-up option is the only choice that gives missing cross-component rules
one home without duplicating accepted topology decisions. It preserves stable
parent boundaries while making failure atomicity, identity, positive transport,
and joint certification explicit. The option comparison and audit grounding
live in `2026-07-19-codebase-health-research`.

## Consequences

- Foreign workers and runtime generations cannot be adopted from health alone.
- Thread deletion becomes retryable and observable, but requires durable
  tombstone and cleanup-manifest state.
- Public local clients must authenticate and migrate to positive progress
  schemas.
- Provider failures terminate predictably, at the cost of additional deadline,
  drain, and cleanup coordination.
- Cross-repository certification takes longer than isolated tests but becomes
  the authoritative release signal.
- The plan must coordinate with three active feature plans before editing their
  shared surfaces.
- Dead-code removal becomes safer because compatibility ownership is checked
  across both repositories.
