---
tags:
  - '#adr'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-30'
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

The delete verb answers with five distinct outcomes, because the service result
distinguishes more states than a two-code surface can carry. Before the saga
begins, a thread whose lifecycle state refuses deletion returns conflict with a
detail - that eligibility refusal is a separate outcome and is not a saga state
at all. A clean deletion returns no content. A deletion that finalized over at
least one cleanup item judged permanently unremovable returns success WITH a
versioned body reporting that cleanup was abandoned and naming the kinds of item
left behind - never their filesystem paths, which are not the caller's to
receive. Genuinely resumable incomplete cleanup returns service-unavailable,
inviting the retry that will in fact make progress. An already-absent thread
returns not-found.

Only two of those are terminal saga states. Resumable-incomplete is explicitly
non-terminal - that is the entire reason it earns a retryable code - and
not-found describes the absence of a saga rather than one of its states. The
grounds for the five-outcome surface is the service result's own vocabulary, not
a count of terminal states.

The abandoned case is deliberately NOT service-unavailable. Its rows are already
gone, so a retry answers not-found; telling a client to retry a completed
deletion would be an incoherent contract. It is equally not a bare success: a
deletion that stranded external artifacts is a terminal fact, and recording it
only in a server log leaves the product unable to surface remediation and any
client-side reconciliation reading the thread as cleanly gone. The guarantee this
surface makes is therefore precise: any success means the deletion is durable and
the control rows are gone, and a success carrying a body additionally means
external state was left stranded.

Naming the item kinds is required, not optional, so the service result carries
the abandoned items through from the finalize outcome rather than flattening them
to a flag.

A consumer asserting strictly on the no-content code will misclassify the
abandoned case. That break is accepted deliberately on this transition surface
rather than preserving a contract that cannot express the outcome.


The retry invitation carried by the resumable-incomplete answer is addressed to the
CALLER, and intermediaries do not loop on it. Automatic retry with backoff is the right
default for a transient fault whose repetition is a cheap, side-effect-free replay - but
this answer is neither. Each delete request claims the saga and drives the full cleanup
manifest against real stores, and each recorded failure advances an attempt ledger whose
ceiling abandons the item permanently. That ceiling assumes retries arrive as separate
requests, spaced widely enough for a transient cause - a briefly-held file, a restarting
store - to clear. A client looping at seconds-scale would exhaust the ceiling against the
same unchanged cause and finalize over stranded state, converting the resumable outcome
into the abandoned one invisibly, inside a blocking call. One sub-case of this answer means
another pass merely holds the claim, whose lease is minutes long, so a fast loop performs
no work at all while occupying its caller.

The surface therefore declares the condition rather than absorbing it: a consumer is told
the deletion is in progress, that the state is resumable and not a server fault, that
repeating the same request resumes the same saga and makes progress, and that persistent
incompleteness will eventually be reported as abandoned. Pacing belongs to whichever layer
knows whether the work is still wanted, which is the caller, not the transport between
them. This boundary would move if the resumable pass became a poll that does not advance
the ledger against an unchanged cause, or if the answer carried a server-computed pacing
hint - either would make a single bounded client retry defensible.

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

Credential VALUES are not part of a run's work identity. Actor tokens and the
engine bearer authorize a request instance rather than describe the work, which
is the classification the fingerprint already applies to the fields that identify
a request rather than describe it. Credential COVERAGE is a different question
and remains enforced where it belongs: admission evaluates role coverage at first
start and refuses an uncovering bundle outright. The fingerprint is the wrong
instrument for coverage in either case.

The plain-start fingerprint therefore excludes credential values. A replay
returns the ORIGINAL run, so a retry's presented bundle is never the bundle that
run uses. Short-lived credentials are expected to rotate across a retry, so
fingerprinting them would refuse precisely the lost-acknowledgement recovery that
client-supplied idempotency exists to serve. Because the classification is named
rather than derived, it is recorded here rather than left to the reader of the
digest helper.

The staged commit binding is deliberately stricter and is unchanged. Its digest
is compared against the durably bound accepted request under per-run
single-flight, so a commit retry carrying a rotated bundle is REFUSED by design
at the credential-binding boundary rather than being impossible; the certified
driver mints once per run and does not rotate inside that window. That deliberate
refusal is the reason the commit digest stays strict.

Persisted fingerprints carry the rule they were computed under, so a run stored
before this classification is compared under the older rule. Raw tokens are never
persisted and a stored fingerprint cannot be recomputed, so without that marker a
byte-identical replay of an older run would be refused spuriously.

The progress channel is a CLOSED per-event catalog rather than an aggregate
snapshot. Every frame type the product emits is enumerated with an explicit
per-field allowlist and explicit bounds on its text fields; a frame type absent
from the catalog is projected onto the always-safe identity keys rather than
passed through, and the frame byte cap remains the backstop. Projection is by
omission and truncation, never refusal: on a channel whose frames are
contractually droppable, degrading an unrecognised frame to its identity keys
preserves the most useful signal, whereas refusing it deletes the frame outright
and turns additive producer evolution into silent loss. The channel still never
carries prompts, document bodies, raw provider payloads, artifact bodies, or edit
diffs, and durable state remains available through `run-status`.

The catalog is closed against evidence of what the product consumes, not against
assumption. Enumerating every emitted type BEFORE flipping the unknown-type
default is what keeps the flip non-breaking: an unenumerated content-bearing type
would otherwise lose its content the moment the default changed.

The aggregate progress schema - counters, explicitly approved summaries, and a
single bounded token-delta field - is WITHDRAWN. It was never constructed by any
production path, and a dashboard consumption inventory confirms no consumer
mirrors it, expects a token delta, or maintains any token-accounting surface at
all, so its removal takes nothing off any wire. The paired-amendment requirement
that guarded the token-delta field is satisfied by that evidence rather than
waived. The token stream the product actually renders is the per-event message
content, which is retained and bounded, and the phase field the product reads
lives on the run-status envelope, which is a different object and is unaffected.

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
