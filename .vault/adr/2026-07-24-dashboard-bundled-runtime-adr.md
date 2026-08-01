---
tags:
  - "#adr"
  - "#dashboard-bundled-runtime"
date: '2026-07-24'
related:
  - '[[2026-07-24-dashboard-bundled-runtime-reference]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-21-capsule-install-layout-adr]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-adr]]'
  - '[[2026-07-18-desktop-product-profile-plan]]'
supersedes:
  - '2026-07-21-capsule-install-layout-adr'
modified: '2026-07-24'
body_hash: 'sha256:0c59a12a444838254a7d6aee535a353d876d9d9c2873b32909b5b519a9e333a2'
---
# `dashboard-bundled-runtime` adr: `a2a is a dashboard-bundled runtime, not an installable product` | (**status:** `accepted`)

## Problem Statement

The desktop-product-profile lineage grew a full end-user distribution apparatus
inside this repository: capsule assembly, archive projection, installed
inventories, dependency-closure verification, license aggregation, evidence
chains, a capsule manifest schema, multi-target packaging scripts, and a
dedicated capsule CI workflow. That apparatus answers a question the owner has
now ruled out: a2a is never installed by an end user. The separate dashboard
project is the only consumer; it builds, bundles, launches, and manages the a2a
service itself. The dashboard-side consume path was never wired (its release
fetch is a fail-closed placeholder), so no live contract breaks. A decision is
needed now because roughly 33,000 lines of packaging machinery, its CI, and its
vault planning waves continue to absorb work and reviews while pointing at a
product shape that will not ship.

## Considerations

- The owner's direction is explicit: the dashboard wants a bundled binary it can
  call to set up and manage the service - start, stop, serve, status, robust
  restart. Nothing simpler exists for the dashboard than owning that binary.
- The dashboard-side provisioning record rejected freezing a2a into a single
  executable solely because worker and provider contracts re-exec
  `sys.executable` with module and snippet arguments; it named the required fix
  itself: an a2a-internal process-model redesign.
- No production module imports the packaging modules; the packaging surface is a
  clean seam (two prior read-only audits; the removal inventory is recorded in
  the pivot execution trail).
- The runtime contract the dashboard already codes against - service discovery
  record, owner-ACL bearer handoff, authenticated health, readiness, drain, and
  shutdown - is independent of distribution shape and must survive unchanged.
- Cross-release schema work (Alembic head, checkpoint schema identity,
  state-driven-development backfill) is needed regardless of how bytes arrive
  on disk: swapping a binary generation still leaves the previous generation's
  SQLite schema behind. The dashboard's own update transaction owns ordering
  and performs consistency-group snapshot and rollback itself as byte-level
  file copies in Rust; it spawns a2a only for the migrate step (dashboard
  source, read-only audit).
- The gateway, worker, provider subprocesses, and MCP bridges are one dependency
  closure in one interpreter today; the freeze boundary must preserve every
  subprocess seam.

## Considered options

- **Dashboard-bundled single runnable binary with a service-management CLI -
  chosen.** a2a stays clean gateway source; the repo ships a wheel and a freeze
  recipe; the dashboard builds and bundles the binary per target and manages it
  through the CLI verbs.
- **Keep the capsule apparatus - rejected.** It is a parallel product with its
  own installer semantics, evidence chain, and CI, serving no consumer; the
  dashboard explicitly does not want to interpret a2a's internal layout.
- **Ship only a wheel and let the dashboard assemble a Python environment -
  rejected.** Reintroduces system-Python, virtual-environment, and offline
  problems the dashboard side already rejected, and leaves interpreter and
  closure guarantees outside product ownership.
- **Nuitka compilation - rejected.** Compile times and native-wheel brittleness
  across targets are unjustified for a bundled companion; PyInstaller freezes
  the existing closure as-is.
- **PyInstaller onefile - rejected.** A long-lived service must not self-extract
  to a temporary directory on every boot; extraction latency also taxes every
  worker respawn, and antivirus heuristics flag onefile more aggressively.
  Onedir is the correct shape for a bundled directory the dashboard ships
  anyway.

## Constraints

- The runtime contract is frozen: discovery record schema, bearer handoff, and
  the authenticated health, readiness, drain, and shutdown verbs must behave
  identically from source and from the frozen binary.
- Every production subprocess re-exec must route through one frozen-aware
  command authority; a frozen binary has no module flag, no inline-snippet
  flag, and no separate interpreter to borrow.
- `vaultspec-core` is a declared dependency and freezes into the binary;
  workspace provisioning must invoke it through the binary's own dispatch, not
  through an ambient interpreter.
- The wheel remains buildable and installable for development and CI; freezing
  is additive, not a replacement for the source distribution.
- Dashboard-side records still describe the capsule consume path; reversing
  them is a cross-repo action outside this record's authority and is proposed
  to the dashboard project separately.

## Implementation

The packaging apparatus is removed whole: the capsule assembly, archive,
inventory, closure, evidence, license, materializer, descriptor, install-layout,
wheel-compatibility, lock-reconciliation, manifest-emission, and package-archive
modules, their unit and service tests, the capsule preparation, build, and
verify scripts and their inputs, the capsule manifest schema and its wheel
force-include, and the capsule CI workflow. The desktop package facade slims to
the component contract surface it still owns.

The runtime seam is kept intact: desktop profile and credentials, platform ACL
and filesystem authority, settlement, the component contract, lifecycle
discovery, gateway auth, and workspace provisioning. Of the former
state-lifecycle machinery only the schema authority survives, reshaped into a
lean dashboard-spawnable migrate entrypoint (packaged-head upgrade with
optional fail-closed base and head assertions, refusing live or locked
stores) plus fresh-store initialisation for setup. The consistency-group
snapshot module, the one-time transaction descriptor ceremony, and their CLI
verbs are deleted: the dashboard performs snapshot, rollback, and transaction
ordering itself and never invokes them - post-strip they had no caller
outside their own tests.

The service-management CLI completes over the existing lifecycle primitives with
no second code path: serve (existing, foreground), setup (application-home
provisioning and fresh-store initialization), start (detached self-spawn,
ready-gated on a live owned listener), stop (authenticated drain and shutdown
via discovery and bearer, tree-kill fallback), status (discovery plus health
probe, machine-readable), and restart (stop with confirmed termination, then
ready-gated start).

The process model becomes freeze-safe through one command authority that renders
"re-exec myself with a subcommand": under a frozen runtime it returns the binary
itself plus dispatch arguments; under source it returns the interpreter plus the
module entry. The worker spawn, the agent-client-protocol authoring stdio bridge
(and its config-home admission validator), the desktop serve re-exec, and the
`vaultspec-core` provisioning spawns all route through it, backed by hidden
dispatch subcommands on the main CLI. The repo ships the PyInstaller onedir spec
and a build entry the dashboard's release pipeline invokes per target.

## Rationale

The winning option is the only one that matches the actual consumer. There is
exactly one consumer, it is a build system, and it asked for a binary with
lifecycle verbs. Every alternative preserves machinery whose purpose was
multi-channel end-user installation - a requirement that no longer exists. The
freezer objection recorded on the dashboard side is not an argument against the
binary; it is the specification of the one real blocker, and the command
authority plus argv dispatch resolves it at a single seam. Keeping only the
migrate authority while deleting snapshot and transaction follows the caller
evidence on both sides: the dashboard's transaction owns snapshot, rollback,
and ordering itself and spawns a2a solely for the migrate step, and once the
capsule flow left the tree, a2a's snapshot and descriptor modules had no
production caller at all.

## Consequences

- This record supersedes the desktop-product-profile capsule direction, the
  capsule-install-layout record, and the capsule waves of the
  desktop-product-profile plan; their non-capsule runtime decisions (profile
  seating, credentials, singleton, settlement) remain in force and are re-homed
  under this record.
- The artifact-lifecycle record loses its capsule-artifact subjects; its
  retention rule survives for runtime artifacts and is narrowed rather than
  superseded.
- Roughly 33,000 lines of packaging code, tests, scripts, schema, and CI leave
  the tree; review and CI bandwidth returns to the runtime.
- The dashboard gains a single, stable management surface and owns target
  matrices, signing, and bundling; a2a stops pretending to be a product.
- Freezing adds a new failure class (hidden imports, data files) contained by
  the in-repo spec plus a smoke gate that boots the frozen binary's dispatch
  paths.
- Dashboard-side records describing capsule consumption must be reversed in
  that repository; until then their consume path remains the fail-closed
  placeholder it already is.
