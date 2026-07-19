---
tags:
  - '#plan'
  - '#desktop-product-profile'
date: '2026-07-18'
modified: '2026-07-19'
tier: L3
related:
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-18-desktop-product-profile-research]]'
  - '[[2026-07-18-desktop-product-profile-reference]]'
---

<!-- RETIRED: P15, S88 -->

# `desktop-product-profile` plan

Ship a target-specific, authenticated, transactional A2A desktop capsule while
preserving the existing Compose server profile and caller-owned standalone MCP
surface.

## Description

This L3 plan implements the accepted
`2026-07-18-desktop-product-profile-adr`, grounded by its Research and
Reference. L3 is required because the work crosses packaging, configuration,
database, gateway, worker, provider, process-control, service-test, and release
workflow boundaries with hard ordering across multiple sessions. L4 is not
valid because no external milestone, project board, or roadmap artifact has
been declared, and this plan does not invent one.

Wave `W01` produces the deterministic A2A handoff consumed by dashboard
packaging: a locked dependency closure, package-owned migrations and presets,
capsule-owned Node.js and ACP assets, a versioned component schema, a pinned
component identity, and verified target archives. The dashboard release
manifest binds that emitted capsule. It must never scrape mutable A2A `main`,
infer package layout, or resolve dependencies while assembling the product.
The component contract declares both the dashboard-owned gateway entrypoint and
the shipped caller-owned `vaultspec-mcp` entrypoint. A2A owns the component
manifest schema and fixtures; the dashboard owns the complete release-set
schema, receipt, and activation transaction. A real fixture at this boundary
prevents either repository from inferring the other's internal layout.

Wave `W02` makes all mutable state explicit and provides the staged migration
and consistency-group primitives used by the dashboard external updater. Wave
`W03` establishes runtime ownership, authentication, secret-free discovery,
and shared readiness. Wave `W04` enforces lazy worker ownership, bounded drain,
whole-tree cleanup, and two-stage prepare and commit semantics under the
existing run-start verb. Prepare may start the gateway-owned lazy worker, but it
creates no durable run, accepts no actor tokens, and creates no run-owned child.
Commit binds dashboard-minted actor tokens to a stable run and non-secret lease
identity. Authenticated terminal settlement lets the dashboard revoke that
lease, while status reconciliation covers dashboard restart.
Wave `W05` certifies real artifacts on all five target triples and proves the
Compose server topology remains intact.

Core runtime and security Steps in Waves `W01` through `W04` require
`vaultspec-high-executor`; isolated build, workflow, and test-harness Steps may
use `vaultspec-standard-executor`. Phase `W05.P14` ends with independent
`vaultspec-code-reviewer` review. The open
`2026-07-14-a2a-edge-conformance-plan` Steps `W03.P07.S18`, `W03.P08.S20`, and
`W05.P14.S31`, the `tool-cores` Steps `P04.S20` and `P04.S21`, and the
`kimi-provider` Steps `P05.S16` through `P05.S18` retain their own ownership.
This plan neither duplicates nor closes them; final product certification
reports any genuine credential or upstream provider gate honestly. The active
`2026-07-14-adr-authoring-orchestration-plan` separately retains ownership of
the untracked `vaultspec-adr-research-mock.toml` fixture, the standing AUTO,
MIXED, and HUMAN reruns, and the intermittent
`checkpoint_permission_without_durable_row` and
`execution_state_projection_missing` defects. Both named defects block release
until that owning plan resolves them; desktop certification cannot waive,
re-attribute, or silently absorb that work.

## Steps

## Wave `W01` - close the desktop capsule boundary

Deliver the target-independent dependency, package-resource, component-manifest, and capsule assembly contract that every later desktop runtime Wave consumes; this implements the accepted profile and artifact boundary.

### Phase `W01.P01` - separate the desktop dependency profile

Make the desktop runtime closure explicit, target-resolvable, and free of runtime acquisition while retaining optional server and development capabilities.

- [x] `W01.P01.S01` - Split install metadata into a Torch- and RAG-free desktop runtime closure plus explicit optional capability groups; `pyproject.toml`.
- [x] `W01.P01.S93` - Guard optional OTLP exporter detection so the desktop base initializes gateway and worker telemetry without server extras and prove it from a clean base installation; `src/vaultspec_a2a/telemetry`.
- [x] `W01.P01.S02` - Regenerate the locked Python graph and prove CPython 3.13 resolution for every accepted target; `uv.lock`.
- [x] `W01.P01.S03` - Lock ACP 0.59.0 and eliminate stale JavaScript adapter identities from the Node closure; `package-lock.json`.
- [x] `W01.P01.S04` - Disable runtime uvx acquisition in the desktop profile and return an actionable unavailable capability result; `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [x] `W01.P01.S05` - Prove installed desktop metadata excludes Torch and RAG while optional profiles remain resolvable; `src/vaultspec_a2a/desktop_tests/test_dependency_closure.py`.

### Phase `W01.P02` - package every capsule-owned runtime asset

Move migrations, presets, Node.js adapter resolution, and component metadata behind installed package or capsule authorities.

- [ ] `W01.P02.S06` - Declare migrations presets and desktop runtime metadata as explicit wheel package data; `pyproject.toml`.
- [x] `W01.P02.S07` - Resolve Alembic configuration and migration scripts from installed package resources; `src/vaultspec_a2a/database/migrate.py`.
- [x] `W01.P02.S08` - Load bundled agent and team presets through package-owned resource paths; `src/vaultspec_a2a/team/team_config.py`.
- [ ] `W01.P02.S09` - Resolve the default Node and ACP adapter only from capsule-owned assets in the desktop profile; `src/vaultspec_a2a/providers/factory.py`.
- [ ] `W01.P02.S10` - Define the versioned desktop component manifest contract consumed by dashboard packaging; `schemas/desktop-capsule-manifest.json`.
- [ ] `W01.P02.S11` - Emit pinned component identity target compatibility gateway and standalone MCP entrypoints digests assets licenses and dependency-lock identity; `src/vaultspec_a2a/desktop/manifest.py`.
- [ ] `W01.P02.S12` - Prove a clean built wheel contains package assets excludes tests and satisfies a real dashboard release-manifest fixture by pinned identity; `src/vaultspec_a2a/desktop_tests/test_component_contract.py`.

### Phase `W01.P03` - assemble and verify five target capsules

Produce reproducible component artifacts for each accepted target triple with digests, licenses, and software bill of materials evidence.

- [ ] `W01.P03.S13` - Assemble a deterministic target capsule from pinned Python Node ACP and package-owned inputs; `scripts/build_desktop_capsule.py`.
- [ ] `W01.P03.S14` - Verify capsule identity target closure entrypoints digests licenses and software bill of materials without a source checkout; `scripts/verify_desktop_capsule.py`.
- [ ] `W01.P03.S15` - Create the artifact workflow that publishes deterministic component archives and manifests for dashboard consumption; `.github/workflows/desktop-capsule.yml`.

## Wave `W02` - establish transactional desktop state

Deliver explicit mutable-state seating, schema validation, staged migration, and consistency-group snapshot primitives after the capsule contract exists; dashboard activation depends on these entrypoints.

### Phase `W02.P04` - seat every mutable desktop path explicitly

Define one desktop profile whose databases, checkpoints, credentials, discovery, receipts, logs, workspaces, temporary homes, and snapshots never derive from the launch directory.

- [ ] `W02.P04.S16` - Define the desktop profile and validate explicit immutable and mutable product roots; `src/vaultspec_a2a/desktop/profile.py`.
- [ ] `W02.P04.S17` - Derive database checkpoint log credential discovery receipt workspace temporary-home and snapshot paths only from the explicit desktop app home; `src/vaultspec_a2a/control/config.py`.
- [ ] `W02.P04.S18` - Add the manifest-declared desktop gateway invocation without changing Compose or foreground serve defaults; `src/vaultspec_a2a/cli/main.py`.
- [ ] `W02.P04.S19` - Prove desktop state remains app-home-seated across launch-directory changes and capsule relocation; `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`.

### Phase `W02.P05` - separate schema validation from migration

Keep ordinary desktop gateway boot non-mutating while exposing one package-local staged-generation migration entrypoint for the external updater.

- [ ] `W02.P05.S20` - Make ordinary desktop database checkpointer and SDD initialization validate compatibility without schema mutation; `src/vaultspec_a2a/database/`.
- [ ] `W02.P05.S21` - Validate the updater one-time descriptor owned state roots and compatible schema range before lifecycle mutation; `src/vaultspec_a2a/desktop/transaction.py`.
- [ ] `W02.P05.S22` - Implement the staged-generation Alembic SDD-backfill and checkpoint migration entrypoint with bounded machine-readable results; `src/vaultspec_a2a/desktop/migration.py`.
- [ ] `W02.P05.S23` - Expose the internal desktop migrate command while keeping lifecycle verbs off the public run-control API; `src/vaultspec_a2a/cli/main.py`.
- [ ] `W02.P05.S24` - Run package-local migrations from a clean installed capsule and reject incompatible or live-store attempts; `src/vaultspec_a2a/desktop_tests/test_migration_entrypoint.py`.

### Phase `W02.P06` - snapshot and restore a consistency group

Capture and restore primary, checkpoint, and declared schema-bearing stores as one receipt-verifiable group after quiescence.

- [ ] `W02.P06.S25` - Create temp-fsynced atomic snapshot descriptors and quiesced restore markers for every declared consistency-group store; `src/vaultspec_a2a/desktop/snapshot.py`.
- [ ] `W02.P06.S26` - Bind mutable-store membership derivability and schema versions into the component manifest; `src/vaultspec_a2a/desktop/manifest.py`.
- [ ] `W02.P06.S27` - Expose bounded snapshot inspect and restore commands for the external updater transaction; `src/vaultspec_a2a/cli/main.py`.
- [ ] `W02.P06.S28` - Prove primary and checkpoint databases restore together from a real consistency group; `src/vaultspec_a2a/desktop_tests/test_snapshot_group.py`.
- [ ] `W02.P06.S29` - Prove interrupted snapshot or restore never exposes a partially committed group; `src/vaultspec_a2a/desktop_tests/test_snapshot_recovery.py`.

## Wave `W03` - bind runtime identity and authenticated readiness

Harden the desktop gateway with a lifetime singleton, secret-free discovery, split credentials, loopback-only exposure, and one readiness model; process admission cannot depend on the runtime until this Wave lands.

### Phase `W03.P07` - acquire singleton ownership before publication

Establish an operating-system-held runtime identity before listener publication and refuse live foreign or unverifiable residents without adopting them.

- [ ] `W03.P07.S30` - Implement the cross-platform lifetime singleton and owner-matching stale-lock classification for one desktop app home; `src/vaultspec_a2a/lifecycle/singleton.py`.
- [ ] `W03.P07.S31` - Replace token-bearing discovery with an atomic versioned profile generation protocol schema owner and ACL-reference record; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [ ] `W03.P07.S32` - Parse the versioned secret-free gateway discovery record without weakening engine authoring discovery; `src/vaultspec_a2a/authoring/discovery.py`.
- [ ] `W03.P07.S33` - Acquire the desktop singleton before invoking Uvicorn socket bind and pass its ownership into gateway startup; `src/vaultspec_a2a/cli/main.py`.
- [ ] `W03.P07.S34` - Prove two real desktop gateway processes cannot own or overwrite one app home; `src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py`.
- [ ] `W03.P07.S35` - Prove authenticated foreign attachment stale-owner recovery and immutable live-conflict behavior with real processes; `src/vaultspec_a2a/desktop_tests/test_discovery_ownership.py`.

### Phase `W03.P08` - separate attach control and worker credentials

Protect versioned product APIs and administrative operations with distinct owner-scoped credentials while keeping the worker IPC secret private to the gateway-worker pair.

- [ ] `W03.P08.S36` - Validate dashboard-created attach and ownership files and create a distinct gateway-owned worker IPC credential with platform ACL checks; `src/vaultspec_a2a/desktop/credentials.py`.
- [ ] `W03.P08.S37` - Model distinct attach credential worker IPC credential and receipt-bound lifecycle capability references; `src/vaultspec_a2a/control/config.py`.
- [ ] `W03.P08.S38` - Implement constant-time attach and lifecycle capability dependencies with redacted failures; `src/vaultspec_a2a/api/dependencies.py`.
- [ ] `W03.P08.S39` - Require the attach credential on the versioned five-verb run-control router without adding verbs; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W03.P08.S40` - Require attach authentication on dashboard product APIs while leaving minimal liveness ungated; `src/vaultspec_a2a/api/routes/__init__.py`.
- [ ] `W03.P08.S41` - Require attach authentication before accepting desktop event WebSockets; `src/vaultspec_a2a/api/app.py`.
- [ ] `W03.P08.S42` - Require both authenticated runtime control and receipt ownership for administrative shutdown; `src/vaultspec_a2a/api/routes/admin.py`.
- [ ] `W03.P08.S43` - Enforce the worker IPC credential on dispatch events heartbeats health and administration; `src/vaultspec_a2a/worker/app.py`.
- [ ] `W03.P08.S44` - Use only the worker IPC credential for gateway-facing event heartbeat and health traffic; `src/vaultspec_a2a/api/internal.py`.
- [ ] `W03.P08.S45` - Read owner-scoped credential files for operator calls without accepting secret command-line arguments; `src/vaultspec_a2a/cli/main.py`.
- [ ] `W03.P08.S46` - Prove attach-control worker IPC and lifecycle credentials are non-interchangeable rejected outside their planes and absent from discovery logs and responses; `src/vaultspec_a2a/desktop_tests/test_credential_boundaries.py`.

### Phase `W03.P09` - serve one desktop readiness model

Expose liveness, gateway readiness, worker state, provider eligibility, and run admission as separate bounded facts shared by discovery and service-state consumers.

- [ ] `W03.P09.S47` - Define separate liveness gateway readiness worker state provider eligibility and run-admission fields; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W03.P09.S48` - Make a valid desktop database with a cold startable worker gateway-ready without claiming execution readiness; `src/vaultspec_a2a/control/health.py`.
- [ ] `W03.P09.S49` - Return only a minimal alive or not-alive signal from unauthenticated HTTP liveness and return process and product identity plus state only from authenticated readiness responses; `src/vaultspec_a2a/api/app.py`.
- [ ] `W03.P09.S50` - Serve the same authenticated readiness facts through service-state and discovery probes; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W03.P09.S51` - Prove unauthenticated HTTP liveness exposes only the minimal alive or not-alive signal and authenticated readiness responses carry process and product identity plus cold-to-execution state; `src/vaultspec_a2a/desktop_tests/test_readiness_model.py`.

## Wave `W04` - enforce process and run ownership

Make the gateway the sole desktop worker owner, defer worker startup to execution demand, drain admission, contain descendants, and preserve the caller-owned standalone MCP boundary after authenticated runtime identity is available.

### Phase `W04.P10` - make worker startup truly demand-driven

Remove desktop boot and reconciliation spawn paths while preserving Compose standalone-worker behavior and atomic first-demand startup.

- [ ] `W04.P10.S52` - Keep desktop boot and redispatch reconciliation from spawning a worker while preserving Compose startup behavior; `src/vaultspec_a2a/api/app.py`.
- [ ] `W04.P10.S53` - Require a desktop gateway to spawn and own its worker without discovering adopting or evicting a Compose worker; `src/vaultspec_a2a/control/worker_management.py`.
- [ ] `W04.P10.S54` - Trigger deferred reconciliation only after authenticated execution demand has completed worker single-flight readiness; `src/vaultspec_a2a/control/dispatch.py`.
- [ ] `W04.P10.S55` - Prove concurrent first demand creates one real worker and idle desktop boot creates none; `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py`.

### Phase `W04.P11` - drain and terminate every owned descendant

Close run admission, bound cancellation, and reap the gateway-owned worker plus
every run-owned provider root, terminal, authoring and projected project MCP,
and harness descendant on every terminal path.

The CLI-preserved `S89` through `S92` identifiers are intentionally interposed
before `S62`; document order keeps each spawn or configuration hardening Step
ahead of the integrated real-descendant proof.

- [ ] `W04.P11.S56` - Implement a bounded drain gate that atomically closes admission tracks active runs and reports quiescence; `src/vaultspec_a2a/control/drain.py`.
- [ ] `W04.P11.S57` - Apply the drain gate to run start cancellation and administrative stop paths; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W04.P11.S58` - Retain actor tokens through INPUT_REQUIRED and release active-run ownership tokens and child handles only on terminal outcomes; `src/vaultspec_a2a/worker/executor.py`.
- [ ] `W04.P11.S59` - Spawn the desktop worker in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work and retain containment for bounded shutdown; `src/vaultspec_a2a/control/worker_management.py`.
- [ ] `W04.P11.S60` - Spawn each run-owned ACP or Codex provider root in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work; `src/vaultspec_a2a/providers/_subprocess.py`.
- [ ] `W04.P11.S61` - Terminate owned POSIX process groups with bounded killpg SIGTERM-to-SIGKILL escalation and assigned Windows Job Objects or equivalently proven OS-owned jobs or trees without recursive process discovery; `src/vaultspec_a2a/utils/process.py`.
- [ ] `W04.P11.S89` - Audit and harden ACP terminal children to inherit the owning run containment and bounded reaper; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [ ] `W04.P11.S90` - Audit and harden per-run authoring MCP launch specifications to remain descendants of the owning provider group; `src/vaultspec_a2a/providers/_acp_authoring.py`.
- [ ] `W04.P11.S91` - Audit and harden projected project MCP configuration so only run-owned launch specifications enter the isolated provider tree; `src/vaultspec_a2a/providers/_acp_project_mcp.py`.
- [ ] `W04.P11.S92` - Audit and harden declared harness MCP launch specifications to inherit the owning ACP or Codex provider group; `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [ ] `W04.P11.S62` - Prove real worker provider terminal authoring projected-project MCP and harness descendants are contained before work and reaped on every graceful and forced terminal path without recursive process discovery; `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`.

### Phase `W04.P12` - admit runs only after execution readiness

Require worker and provider eligibility before durable run creation or actor-token acceptance, and keep standalone MCP outside the desktop lifecycle tree.

- [ ] `W04.P12.S63` - Define prepare and commit variants bounded required-role output reservation identity lease identity and terminal settlement under run-start; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W04.P12.S64` - Implement hard-bounded expiring prepare reservations that validate required roles capacity worker startup and provider readiness without run-owned children or durable runs; `src/vaultspec_a2a/control/admission.py`.
- [ ] `W04.P12.S65` - Implement prepare and commit through the existing POST /v1/runs verb without durable state before commit; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W04.P12.S66` - Evaluate worker and provider eligibility before accepting actor tokens or creating a run; `src/vaultspec_a2a/control/run_start_policy.py`.
- [ ] `W04.P12.S67` - Emit bounded terminal callbacks authenticated with the dashboard-created attach-control credential read by the gateway and containing run and non-secret lease identities only; `src/vaultspec_a2a/desktop/settlement.py`.
- [ ] `W04.P12.S68` - Trigger the attach-control-authenticated settlement component idempotently after execution-state persistence on complete cancel and fail without exposing or requiring worker IPC; `src/vaultspec_a2a/control/event_handlers.py`.
- [ ] `W04.P12.S69` - Prove prepare timeout cancellation and failed commit release capacity without a run token or run-owned child process; `src/vaultspec_a2a/desktop_tests/test_run_admission.py`.
- [ ] `W04.P12.S70` - Prove attach-control-authenticated terminal callback retry rejects worker IPC and unrelated credentials while status reconciliation revokes exactly one run-scoped lease without raw tokens; `src/vaultspec_a2a/desktop_tests/test_terminal_settlement.py`.
- [ ] `W04.P12.S71` - Certify a clean installed capsule starts and stops the standalone vaultspec-mcp adapter under caller ownership; `src/vaultspec_a2a/desktop_tests/test_standalone_mcp.py`.

## Wave `W05` - certify artifacts without regressing Compose

Exercise real installed artifacts, operating-system processes, mutable-state recovery, target closure, and the unchanged Compose server profile; dashboard product and channel certification consumes this evidence.

### Phase `W05.P13` - prove the desktop artifact lifecycle

Run real-behavior capsule, security, state, process, and default-provider scenarios without fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures.

- [ ] `W05.P13.S72` - Build a real-process harness that installs invokes relocates and inspects a published desktop capsule; `src/vaultspec_a2a/desktop_tests/harness.py`.
- [ ] `W05.P13.S73` - Prove clean offline install relocation cold readiness lazy worker and default ACP execution from one real capsule; `src/vaultspec_a2a/desktop_tests/test_artifact_install.py`.
- [ ] `W05.P13.S74` - Prove migration rollback consistency restore tamper detection and immutable-file verification from real capsule state; `src/vaultspec_a2a/desktop_tests/test_artifact_state_lifecycle.py`.
- [ ] `W05.P13.S75` - Prove authenticated attach owner-only shutdown drain and data-preserving capsule removal boundaries; `src/vaultspec_a2a/desktop_tests/test_artifact_ownership_lifecycle.py`.
- [ ] `W05.P13.S76` - Certify Apple Silicon macOS capsule closure and upload its pinned component contract; `.github/workflows/desktop-capsule.yml`.
- [ ] `W05.P13.S77` - Certify Intel macOS capsule closure and upload its pinned component contract; `.github/workflows/desktop-capsule.yml`.
- [ ] `W05.P13.S78` - Certify Arm64 Linux capsule closure and upload its pinned component contract; `.github/workflows/desktop-capsule.yml`.
- [ ] `W05.P13.S79` - Certify x86-64 Linux capsule closure and upload its pinned component contract; `.github/workflows/desktop-capsule.yml`.
- [ ] `W05.P13.S80` - Certify x86-64 Windows capsule closure and upload its pinned component contract; `.github/workflows/desktop-capsule.yml`.

### Phase `W05.P14` - retain server profile and review gates

Certify Compose gateway-worker separation, PostgreSQL, Jaeger, and the mandatory implementation review while reporting upstream provider gates honestly.

- [ ] `W05.P14.S81` - Authenticate the Compose worker healthcheck without changing its independently managed worker topology; `service/docker-compose.prod.yml`.
- [ ] `W05.P14.S82` - Authenticate the development Compose worker healthcheck without adopting it into desktop lifecycle; `service/docker-compose.dev.yml`.
- [ ] `W05.P14.S83` - Authenticate the integration Compose worker healthcheck while retaining VidaiMock and Jaeger certification; `service/docker-compose.integration.yml`.
- [ ] `W05.P14.S84` - Prove Compose gateway-worker separation PostgreSQL overlay Jaeger and operator lifecycle remain production-capable; `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`.
- [ ] `W05.P14.S85` - Run desktop target and Compose certification as required release checks without expected-failure shortcuts; `.github/workflows/test.yml`.
- [ ] `W05.P14.S86` - Perform the mandatory architecture security resource-bound and real-behavior code review; `.vault/audit/2026-07-18-desktop-product-profile-review-audit.md`.
- [ ] `W05.P14.S87` - Report 2026-07-14-adr-authoring-orchestration-plan ownership of vaultspec-adr-research-mock.toml AUTO MIXED HUMAN reruns checkpoint_permission_without_durable_row and execution_state_projection_missing separately from provider gates; `.vault/audit/2026-07-18-desktop-product-profile-certification-audit.md`.

## Parallelization

Waves are hard ordered. `W01` must publish a verified component contract before
state entrypoints bind to it in `W02`; `W03` depends on explicit state and
credential paths; `W04` depends on authenticated runtime identity; `W05`
certifies the assembled result.

Within `W01`, dependency closure in `P01` and package-resource work in `P02`
may proceed in parallel, but capsule assembly in `P03` waits for both. Within
`W02`, path seating in `P04` lands first; migration and snapshot implementation
may then proceed in parallel against the same declared store contract. Within
`W03`, singleton/discovery and credential implementation may proceed in
parallel after their shared profile fields are fixed; readiness waits for both.
Within `W04`, lazy-worker work and process containment may proceed in parallel;
two-stage run admission waits for their worker-readiness and drain primitives.
In `W05`, the five target jobs are independent after the harness and verifier
land. Compose regression can run alongside the target jobs, while formal review
and certification reporting wait for all implementation and test evidence.

The dashboard repository may implement its typed lifecycle registry, release
manifest, receipt, installer, and external-updater substrate alongside A2A
Waves `W01` through `W03`. Dashboard composite assembly is blocked on A2A
`W01`; update and rollback integration is blocked on `W02`; authenticated
start, attach, and readiness are blocked on `W03`; run-token leasing and
process ownership are blocked on `W04`; product publication is blocked on both
repositories' final artifact certification.

## Verification

The plan is complete only when every Step is closed and all of the following
evidence passes:

- `uv lock --check`, the dependency audit, and clean environment resolution
  prove the desktop closure on Apple Silicon macOS, Intel macOS, Arm64 Linux,
  x86-64 Linux, and x86-64 Windows without Torch or RAG.
- A clean `uv build` wheel contains migrations, presets, schema, and declared
  runtime metadata while excluding packaged tests. The capsule builder consumes
  only pinned inputs and emits deterministic component identity, target,
  entrypoints, digests, licenses, and software bill of materials metadata. A
  real cross-repository fixture proves the dashboard release manifest binds the
  A2A-owned component schema by pinned identity.
- The verifier accepts each published target capsule without a source checkout
  and rejects a wrong target, missing asset, stale lock identity, altered digest,
  undeclared mutable store, or incompatible schema range.
- A relocated capsule starts offline with explicit app-home state. Ordinary
  desktop boot performs no schema mutation, including Alembic upgrade,
  checkpointer setup, or SDD backfill. The staged migration command owns all
  three under a valid one-time transaction descriptor after quiescence. Real
  primary and checkpoint databases snapshot to temp files, fsync, and commit one
  atomic descriptor; a quiesced restore marker governs interruption recovery.
- Two real gateways cannot own one app home. Discovery is atomically published,
  versioned, owner-restricted, and contains no bearer value. The gateway reads
  the dashboard-created attach-control credential for dashboard control and
  terminal callbacks. Worker IPC is separately gateway-created, remains private
  to gateway-worker traffic, and is never exposed to or required by the
  dashboard. Attach-control, worker IPC, and lifecycle ownership credentials are
  rejected outside their planes. Desktop listeners bind only to loopback.
  Unauthenticated liveness returns only a minimal alive or not-alive signal with
  no process identity, product identity, or product state; authenticated
  readiness carries those identity and state facts.
- A cold worker is gateway-ready but not execution-ready. Concurrent prepare
  calls create one worker and enforce a hard reservation bound. Prepare receives
  no tokens, returns a bounded validated required-role set, and creates no run or
  run-owned child. Commit is reservation-bound. INPUT_REQUIRED retains the
  active lease. After durable terminal state, the gateway callback authenticates
  to the dashboard with attach-control and the dashboard rejects worker IPC and
  unrelated credentials. Timeout, cancel, failed commit, dispatch failure,
  completion, and dashboard restart leave no leaked reservation, raw token,
  run-owned process, or unreconciled lease.
- Gateway drain closes admission before bounded cancellation. On POSIX, every
  owned root starts in a new session and process group before descendant work,
  and shutdown escalates over the group with bounded `killpg` SIGTERM then
  SIGKILL. On Windows, every owned root is assigned before descendant work to a
  Job Object or equivalently proven operating-system-owned job or tree with
  bounded termination. Cleanup never depends on best-effort recursive process
  discovery. Real descendant proof covers the gateway-owned worker and every
  run-owned ACP provider, terminal, authoring MCP, projected project MCP, and
  harness MCP descendant. The clean installed `vaultspec-mcp` entrypoint is
  exercised as a separate caller-owned process and is never launched or adopted
  by desktop lifecycle.
- Desktop certification imports production code and observes actual archives,
  files, SQLite stores, sockets, HTTP authentication, process identifiers,
  descendants, discovery records, and callbacks. It uses no fake, mock, stub,
  patch, monkeypatch, skipped case, or expected failure.
- Compose certification proves the independently managed worker, PostgreSQL
  overlay, Jaeger integration, authentication, and operator lifecycle remain
  valid. Desktop code never discovers, adopts, evicts, or terminates that worker.
  The existing foreground development and server migration paths remain
  profile-scoped and operational.
- The dashboard consumes a pinned emitted A2A component contract and binds it in
  a complete release-set manifest. No dashboard build reads mutable A2A source or
  infers capsule internals.
- The final code-review and certification audits contain no unresolved critical
  or high-severity finding. Any credential-dependent or upstream provider proof
  that remains gated is reported as a release blocker and is not substituted by
  metadata-only evidence. The untracked `vaultspec-adr-research-mock.toml`
  fixture, AUTO, MIXED, and HUMAN standing reruns, and intermittent
  `checkpoint_permission_without_durable_row` and
  `execution_state_projection_missing` defects remain owned by the active
  `2026-07-14-adr-authoring-orchestration-plan`; both named defects block
  release. The separate edge-conformance, tool-cores, and Kimi provider proof
  gates remain owned by their respective plans.
