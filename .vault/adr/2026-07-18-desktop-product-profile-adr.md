---
tags:
  - '#adr'
  - '#desktop-product-profile'
date: '2026-07-18'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-research]]"
  - "[[2026-07-18-desktop-product-profile-reference]]"
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-03-04-worker-process-architecture-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-02-28-dependency-hygiene-cli-entry-point-adr]]"
  - "[[2026-03-31-database-migration-framework-adr]]"
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
---

# `desktop-product-profile` adr: `a dashboard-managed companion profile alongside Compose` | (**status:** `accepted`)

## Problem statement

Agent-to-Agent (A2A) must become an installable, offline-capable dashboard
companion. The desktop contract cannot depend on a source checkout, system
Python, Docker Desktop, or runtime dependency resolution. The current wheel and
lifecycle do not form a safely replaceable desktop component. The grounding
lives in `2026-07-18-desktop-product-profile-research` and
`2026-07-18-desktop-product-profile-reference`.

This decision introduces a desktop production profile while preserving Docker
Compose as the server profile. It defines the boundaries shared with the
dashboard's composite distribution.

## Considerations

- Compose remains the accepted server deployment topology. The desktop profile
  must coexist with it (`2026-03-20-service-lifecycle-architecture-adr`).
- Gateway and worker separation remains valuable. Eager worker startup and
  incomplete descendant cleanup are unsuitable for dashboard ownership
  (`2026-07-18-desktop-product-profile-research`).
- A wheel alone does not contain the migrations or provider assets required for a clean runtime (`2026-07-18-desktop-product-profile-reference`).
- System Python, `uvx`, and runtime package downloads cannot establish offline, reproducible product closure (`2026-07-18-desktop-product-profile-research`).
- The desktop base closure must support Apple Silicon macOS, Intel macOS, Arm64
  Linux, x86-64 Linux, and x86-64 Windows. Unconditional Torch and
  retrieval-augmented generation (RAG) dependencies violate that constraint
  (`2026-07-18-desktop-product-profile-research`).
- Discovery currently exposes a worker credential. It also permits multiple
  gateways to claim one application home
  (`2026-07-18-desktop-product-profile-reference`).
- Liveness, gateway readiness, worker state, and provider eligibility are
  distinct facts. One readiness result must not collapse them
  (`2026-07-18-desktop-product-profile-research`).
- SQLite data and other mutable state must survive immutable runtime replacement and failed migration attempts (`2026-07-18-desktop-product-profile-reference`).
- Product certification must exercise built artifacts and real operating-system processes rather than checkout interpreters or test doubles (`2026-07-18-desktop-product-profile-research`).

## Considered options

- **Adjacent target-specific runtime capsule - chosen.** Preserves current
  interpreter and subprocess contracts. It supports independent A2A staging,
  verification, and repair. Activation and rollback always select a compatible
  complete release-set receipt. The option increases artifact size and matrix
  work.
- **Wheel on system Python.** Smallest artifact, but rejected because interpreter availability, package resolution, repository-relative assets, and offline behavior would remain outside product control.
- **Docker-based desktop profile.** Reuses the server topology, but rejected because it imposes an external runtime and lifecycle that cannot be distributed or owned as part of the dashboard installation.
- **Frozen Python executable.** Could reduce visible runtime structure. Rejected
  because current child-process contracts and dynamic behavior require a
  separate compatibility project.
- **Runtime embedded inside the dashboard executable.** Could preserve
  binary-only channels. Rejected because it couples component replacement and
  weakens scoped repair.
- **Bun-compiled provider adapters.** May later reduce the Node payload, but deferred until every target proves equivalent Agent Client Protocol (ACP) resource loading and process behavior. Node.js is the verified baseline.

## Constraints

- The desktop capsule is target-specific and immutable. Its base closure
  contains CPython 3.13, locked A2A, migrations, presets, Node.js 22, and ACP
  0.59.0.
- Torch and RAG are excluded from the desktop base closure. RAG is a separately installed capability whose absence is reported explicitly; neither capability may trigger downloads at runtime.
- The desktop profile may not depend on Docker, a system Python installation, `uv`, `uvx`, npm installation, or network access after installation.
- Mutable databases, checkpoints, logs, credentials, discovery state, receipts, temporary provider homes, and workspaces live outside immutable runtime generations.
- The dashboard controls only the gateway. The gateway controls its worker.
  Each run owns its provider subprocesses and authoring or harness Model Context
  Protocol (MCP) bridges. The standalone MCP adapter remains a separate,
  independently invokable surface.
- Desktop network listeners bind to loopback. Dashboard-control authentication and gateway-worker interprocess communication (IPC) authentication use distinct credentials.
- The gateway acquires a lifetime runtime singleton before bind and discovery.
  A distinct, short-lived installation lock serializes product mutation. A
  non-owner may attach to a compatible service but cannot mutate its lifecycle.
- The existing Compose topology is a stable parent and remains authoritative for
  the server profile. Named host-process development lifecycle is governed by
  `2026-07-15-dev-process-registry-adr`, with its repository command surface
  governed by `2026-07-19-repository-tooling-hardening-adr`. Gateway-worker
  separation and Alembic are also retained. Desktop packaging, discovery,
  readiness, and lifecycle behavior are not stable enough to inherit unchanged
  and are governed by this record.
- Verification may not use fakes, mocks, stubs, patches, monkeypatches, skipped tests, or expected failures as evidence for product lifecycle behavior.

## Implementation

### Product profiles and artifact boundary

A2A gains a `desktop` profile alongside the existing `compose` server profile.
Compose retains its gateway, independently managed worker, PostgreSQL option,
Jaeger integration, and operator lifecycle.

The dashboard's composite installation carries the desktop capsule. Each
generation declares component identity, target, compatibility, digests,
dependency lock, and migration range. The dashboard invokes only supported
lifecycle and gateway entrypoints. It neither imports A2A packages nor depends
on the capsule layout.

The base capsule includes CPython 3.13, A2A, package-local migrations, presets,
Node.js 22, and ACP 0.59.0. Providers resolve capsule-owned assets. Product state
declares optional capabilities. An absent capability returns an actionable
unavailable result and never resolves itself from the network.

### Ownership and process topology

The dashboard lifecycle controller owns one desktop gateway process. The
gateway owns ordinary database initialization, schema validation, discovery,
the worker client, and the worker spawner. A2A exposes migrations through a
dedicated staged-generation lifecycle entrypoint. Only the external updater
invokes that entrypoint after quiescence.

After initialization, the worker retains bounded access to shared task
persistence and its checkpointer. Ordinary gateway boot and reconciliation do
not start it. First execution demand uses a serialized single-flight start.

The invoking run owns provider subprocesses and authoring or harness MCP
bridges. Run completion, cancellation, or failure terminates their process
trees. The invoking operator owns the independently launched standalone MCP
adapter. The desktop lifecycle neither launches nor adopts it.

Gateway drain closes admission before stopping owned workers and run-owned
descendants. Shutdown completes after descendants exit or bounded forced cleanup
finishes.

The Compose profile retains independently managed worker mode. No dashboard lifecycle operation may adopt or terminate a Compose worker.

### Security, singleton, and discovery

The desktop gateway binds only to loopback. Versioned dashboard control and
product application programming interface (API) operations require the attach
credential. A minimal liveness probe may remain unauthenticated. It discloses no
product state and proves neither ownership nor readiness.

Receipt-bound lifecycle operations also require an ownership capability that
discovery never references. This includes administrative shutdown. A foreign
attachment cannot invoke these operations. Worker dispatch and administration
use a separate worker IPC credential. Events, heartbeats, health administration,
and shutdown require the same credential. Discovery never publishes it.

A private operating-system runtime singleton guards one application home for the
gateway lifetime. Discovery follows singleton acquisition, listener bind, schema
validation, and control authentication. Its versioned record identifies the
profile, generation, protocol range, process, endpoint, freshness, and owner. It
also names a non-secret credential-file reference protected by the owner's
operating-system access-control list (ACL). The record discloses no credential.

A contender validates discovery, process identity, compatibility,
authentication, and readiness. It may attach only through the ACL-protected
credential-file reference or equivalent registration capability named by
discovery. A foreign resident without that handoff produces an immutable
conflict. So does a live incompatible, malformed, or unauthenticated resident.
Under the installation transaction lock, the matching receipt owner may
quarantine stale discovery after proving the recorded process dead. Attachment
never confers lifecycle ownership. Only that receipt owner may coordinate
mutation with its authenticated runtime singleton owner.

### Readiness and admission

Desktop health exposes separate bounded facts for process liveness, gateway
readiness, worker state, provider eligibility, and run admission. A live gateway
with a valid database and cold, startable worker is gateway-ready. Worker
absence before demand is informational, not degradation.

The first execution operation enters an atomic, bounded admission path. Worker
startup is single-flight. The broker probes readiness before assigning run
capacity. It mints actor credentials only after the runtime and provider become
eligible. Failed admission revokes partial credentials and leaves no run or
child process behind.

### State, migration, and transactional lifecycle

The capsule and mutable product state have separate authorities. Product
configuration resolves explicit paths for databases, checkpoints, logs,
credentials, discovery, receipts, workspaces, and temporary homes. The desktop
profile forbids launch-directory-relative defaults.

The lifecycle plane exposes typed and bounded operations: install, ensure, start,
stop, restart, repair, update, rollback, remove, and doctor. Mutating operations
on an existing installation require receipt ownership and the installation
transaction lock. First install instead requires a verified candidate manifest
and owner-restricted bootstrap descriptor. It atomically creates the initial
receipt and ownership capability. The controller always acquires the lock first.

For a live owned gateway, the controller authenticates, drains, and stops it.
The controller then waits for runtime-singleton release. For a stopped install
or dead recorded process, it proves absence and quarantines only owner-matching
stale state. The gateway never waits on the installation lock. The controller
holds that lock through activation or rollback.

The dashboard's external updater coordinates update. After acquiring the
installation transaction lock, it drains a live owned gateway. If draining
exceeds its configured timeout, the updater cancels active runs and waits for
them to exit. It then authenticates and stops the gateway. The updater waits for
the worker, run-owned descendants, database connections, and runtime singleton
to exit. If the gateway is absent or dead, it proves that state and quarantines
only owner-matching stale discovery. It then requests dashboard-process exit
and waits for termination.

With the old generation quiescent, the updater snapshots the primary and
checkpoint databases plus every other schema-bearing store as one consistency
group. The updater stages self-installed files; a package-manager adapter makes
its manager stage manager-owned files. The updater verifies the resulting
candidate before file activation. The manager activates manager-owned files;
the updater activates self-installed files. The updater checks protocol and
migration compatibility. It invokes the staged generation's dedicated migration
entrypoint and atomically commits a complete dashboard/A2A release-set receipt.
The updater relaunches the dashboard process. That process starts its owned
gateway, and the updater proves readiness for both components.

Any failure before acceptance stops the candidate dashboard process and its
owned gateway. The updater waits for their processes and runtime singleton to
exit. It invokes the channel's file rollback authority and restores the prior
snapshot group and complete receipt. The updater relaunches the prior dashboard
process and verifies its owned gateway. A store may be omitted only when the
release manifest declares and proves it derivable. Ordinary gateway start
validates schema compatibility but never performs a desktop lifecycle migration.

Repair verifies immutable content against the receipt and replaces damaged
capsule files without overwriting mutable state. Removal drains and removes
owned runtime generations and receipts. Only an explicit data-removal operation
deletes user data.

### Compatibility and prior decisions

This record does not supersede any related architecture decision record (ADR)
wholesale.

For the desktop profile only, this record overrides Compose as the sole
production deployment. It also overrides the accepted absence of a desktop
experience in `2026-03-20-service-lifecycle-architecture-adr`. Docker Compose
remains production for servers. The no-freezer and no-system-service clauses
remain in force.

It narrows the auto-spawn clause in
`2026-03-04-worker-process-architecture-adr`. Desktop ownership remains
parent-child, but spawn moves to first execution demand. Compose retains
standalone worker mode.

It replaces desktop discovery decision R8 in
`2026-07-14-a2a-edge-conformance-adr`. Discovery no longer carries the worker
token. Ungated health proves neither ownership nor readiness. Absent alone does
not grant start permission; the singleton and receipt do. Compatible foreign
instances remain attachable but immutable. The five-verb edge and process split
remain intact.

It extends `2026-02-28-dependency-hygiene-cli-entry-point-adr`. Target closure
and shipped non-Python assets become dependency-hygiene requirements. A wheel,
`uvx`, or import-only audit cannot prove desktop closure. Existing
direct-dependency and telemetry principles remain in force.

It narrows the entry-time migration strategy in
`2026-03-31-database-migration-framework-adr`. Alembic remains the schema
authority. Desktop migrations run only in an owned snapshot-and-rollback
transaction. Compose may retain startup migration.

### Verification

Acceptance installs the real composite artifact on each named target. Every
target proves offline installation, relocation, authenticated startup, and cold
gateway readiness. It also proves single-flight worker startup, real provider
execution, run completion, descendant cleanup, and clean shutdown. A separate
real-process test covers the caller-owned standalone MCP adapter.

The matrix also proves singleton exclusion, safe foreign attachment, stale-owner
recovery, credential separation, and bounded admission. It covers state
persistence, consistency-group restoration, tamper repair, compatible migration,
both rollback paths, removal, and default data preservation.

Every supported channel is tested from its published artifact. Compose receives
regression certification for server topology, standalone workers, PostgreSQL,
and observability.

## Rationale

The adjacent capsule alone preserves the established Python and subprocess
contracts while providing offline target closure. It separates mutable state
from executable generations. It also stages and verifies a new A2A generation
without replacing an unchanged compatible dashboard. Activation and rollback
still select one complete receipt. These requirements come from
`2026-07-18-desktop-product-profile-research`.

Gateway ownership follows authority already concentrated in that process. It
also preserves worker isolation. Lazy worker startup reduces idle cost without
collapsing the split. Each run owns and cleans up its provider and authoring
descendants. The standalone MCP adapter stays outside that tree.

Profile-scoped overrides preserve the validated server deployment. Transactional
ownership, authenticated discovery, and real-artifact verification close the
gaps in `2026-07-18-desktop-product-profile-reference`. Current checkout
behavior no longer stands in for product evidence.

## Consequences

- The dashboard can distribute A2A as one product while retaining component
  identity, staging, verification, and repair. Update and rollback always select
  a complete compatible receipt.
- Desktop users need neither Docker nor a preinstalled Python, Node.js, `uv`, or package manager.
- The base artifact becomes materially larger because it carries two managed runtimes and provider assets.
- Release engineering must build, verify, and retain target-specific capsule
  generations. The existing zero-budget code-signing posture remains in force.
- A2A must maintain two explicit production profiles whose lifecycle and migration behavior differ at their outer boundary.
- RAG and other heavyweight optional capabilities require a separate installation and eligibility experience.
- Gateway APIs that were previously usable without authentication become unavailable to unauthenticated local clients.
- Cold readiness becomes more expressive but requires consumers to stop treating worker absence as service failure.
- Update transactions become more complex because database compatibility, process drain, receipt activation, and rollback are one product invariant.
- The standalone MCP adapter remains independently invokable and therefore requires its own caller-owned lifecycle and certification path.
- The profile creates a stable foundation for later size optimization, including a proven Bun-based provider payload, without making that optimization a prerequisite for shipment.
