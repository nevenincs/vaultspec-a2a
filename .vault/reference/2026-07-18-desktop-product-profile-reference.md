---
tags:
  - '#reference'
  - '#desktop-product-profile'
date: '2026-07-18'
modified: '2026-07-18'
related:
  - "[[2026-07-18-desktop-product-profile-research]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `desktop-product-profile` reference: `runtime, packaging, and lifecycle closure`

This reference maps the current Agent-to-Agent (A2A) runtime, packaging, and
lifecycle seams that govern a desktop product profile. It combines source
inspection at A2A commit
`db7400a287872b4ac1a0f982b383620a9fe0db82` with clean-wheel and live-process
probes performed on 2026-07-18.

## Summary

- The current desktop-shaped runtime is a Python 3.13 gateway and worker with
  SQLite-first persistence, subprocess-backed providers, an independently
  invokable MCP adapter, and invocation-scoped authoring bridges.
- Runtime ownership is concentrated in the gateway, but artifact assembly,
  authentication, singleton enforcement, readiness, shutdown, update, and
  rollback are not yet closed as a desktop product lifecycle.
- The clean wheel and live-runtime probes show that a source checkout remains an
  undeclared prerequisite for important runtime paths.

### Gateway application programming interface (API)

- The gateway owns database initialization, checkpointing, events, worker
  spawning, watchdogs, discovery publication, and shutdown coordination.
  `src/vaultspec_a2a/api/app.py:127-365`
- Singleton detection is warning-only; startup continues after detecting an
  existing instance. `src/vaultspec_a2a/api/app.py:251-266`
- Discovery publication is writable shared state and includes the internal
  worker token. `src/vaultspec_a2a/lifecycle/discovery.py:63-146`
  `src/vaultspec_a2a/lifecycle/discovery.py:205-264`
- Public `/v1` reads require no authentication.
  `src/vaultspec_a2a/api/routes/gateway.py:71`
- Administrative shutdown requires no authentication.
  `src/vaultspec_a2a/api/routes/admin.py:5-14`
- Bind configuration permits non-loopback exposure independently of endpoint
  authentication. `src/vaultspec_a2a/control/config.py:222-244`
- The internal worker token is configuration-derived and is not a dashboard
  control credential. `src/vaultspec_a2a/control/config.py:282-288`

### Worker management

- The worker spawner constructs its lock eagerly, serializes creation through
  that lock, launches the worker with the current Python interpreter, and
  retains an owned process handle.
  `src/vaultspec_a2a/control/worker_management.py:307-315`
  `src/vaultspec_a2a/control/worker_management.py:417-480`
- Boot reconciliation calls worker ensure before demand, so the present gateway
  does not preserve a truly cold lazy-worker state.
  `src/vaultspec_a2a/control/dispatch.py:221-225`
- Worker dispatch and administrative shutdown validate the internal token;
  worker health remains unauthenticated.
  `src/vaultspec_a2a/worker/app.py:203-207`
  `src/vaultspec_a2a/worker/app.py:233-251`
  `src/vaultspec_a2a/worker/app.py:253-267`
- No request-drain phase closes admission before worker or gateway termination.
  `src/vaultspec_a2a/api/app.py:127-365`
  `src/vaultspec_a2a/control/worker_management.py:406-519`
- Live probes observed a worker before gateway readiness converged and an
  orphaned worker after Windows gateway shutdown.

### Protocol and provider processes

- The standalone Model Context Protocol (MCP) adapter is independently invokable
  over standard input/output or streamable Hypertext Transfer Protocol (HTTP)
  and has no product lifecycle owner.
  `src/vaultspec_a2a/protocols/mcp/__main__.py:24-51`
- Agent Client Protocol (ACP) authoring constructs a run-scoped server
  specification; ACP subprocess creation and process-tree cleanup occur per
  model invocation.
  `src/vaultspec_a2a/providers/_acp_authoring.py:247-303`
  `src/vaultspec_a2a/providers/acp_chat_model.py:382-461`
  `src/vaultspec_a2a/providers/acp_chat_model.py:530-578`
- Provider launch commands, executable discovery, environment construction, and
  adapter selection are centralized in the provider factory.
  `src/vaultspec_a2a/providers/factory.py:114-420`
  `src/vaultspec_a2a/providers/factory.py:510-730`
- The default Node adapter resolves a project-root-relative `node_modules`
  asset; a separate experimental binary backend searches package-local `bin/`.
  `src/vaultspec_a2a/providers/factory.py:22-38`
  `src/vaultspec_a2a/providers/factory.py:239-270`
- ACP is pinned to version `0.59.0`. `package.json:7`
- Retrieval-augmented generation (RAG) MCP is launched dynamically through
  `uvx`, adding an external runtime resolution boundary.
  `src/vaultspec_a2a/providers/_acp_mcp.py:32-59`

### Readiness

- Gateway startup readiness, health aggregation, and the public readiness route
  implement overlapping semantics that can disagree.
  `src/vaultspec_a2a/api/app.py:425-456`
  `src/vaultspec_a2a/control/health.py:229-326`
  `src/vaultspec_a2a/api/routes/gateway.py:773-836`
- Provider readiness is independently derived from model-profile configuration
  and provider availability.
  `src/vaultspec_a2a/providers/model_profiles.py:320-425`
  `src/vaultspec_a2a/providers/model_profiles.py:469-559`
- Live probes observed conflicting readiness answers for the same process.

### Database and mutable state

- SQLite is the default product data store, and file-backed database startup
  invokes migrations. `src/vaultspec_a2a/database/session.py:170-180`
- Alembic execution expects migration configuration outside the packaged Python
  module tree. `src/vaultspec_a2a/database/migrate.py:22-43`
- Backup and restore primitives exist in control storage, but they are not yet
  connected to an install, update, rollback, or removal transaction.
  `src/vaultspec_a2a/control/db.py:104-188`
- A2A home covers runtime state, while the default database URL and workspace
  remain launch-context-relative. `src/vaultspec_a2a/control/config.py:29-31`
  `src/vaultspec_a2a/control/config.py:69-76`
  `src/vaultspec_a2a/control/config.py:103`
  `src/vaultspec_a2a/control/config.py:113-120`
- Live probes observed shared-home discovery state overwritten by the most
  recently publishing gateway.

### Deployment topology

- Production Compose defines the gateway, worker, and Jaeger topology.
  `service/docker-compose.prod.yml:14-92`
- The PostgreSQL overlay replaces the SQLite-oriented persistence topology for
  service deployment. `service/docker-compose.prod.postgres.yml:6-52`
- VidaiMock is present only in the integration certification topology.
  `service/docker-compose.integration.yml:87-105`

### Packaging and release closure

- Project metadata requires Python 3.13 and declares the Torch and RAG
  dependency surface; wheel configuration includes the Python package tree.
  `pyproject.toml:1-40` `pyproject.toml:76-77`
- The 2026-07-18 clean wheel was 1,047,997 bytes with 447 archive entries. It
  included the repository's packaged test modules but omitted `alembic.ini`, the
  JavaScript package, `node_modules`, the required default-provider JavaScript
  asset, and the experimental package-local binary.
- Clean-wheel gateway startup exited with status `3`; provider construction
  raised `ConfigError` for missing assets.
- No release workflow assembles, validates, signs, publishes, upgrades, or rolls
  back a complete desktop artifact.

### Product lifecycle surface

- The command-line interface (CLI) exposes operational commands but no complete
  install, upgrade, rollback, service registration, drain, uninstall, or
  product-state lifecycle.
  `src/vaultspec_a2a/cli/main.py:64-457`
- Live probes showed two gateways running against one application home while
  binding to `0.0.0.0`.
- Unauthenticated clients could read public gateway data and request shutdown.
- Discovery overwrite exposed the internal worker token to readers of shared
  mutable state.

### Decision boundaries and gaps

- The accepted service-lifecycle record establishes Compose production and
  explicitly accepts no desktop experience. Desktop authentication, singleton,
  discovery, and lifecycle closure therefore require a coordinated new profile
  or amendment rather than being governed by that record.
  `.vault/adr/2026-03-20-service-lifecycle-architecture-adr.md:62-120`
  `.vault/adr/2026-03-20-service-lifecycle-architecture-adr.md:230-234`
- Gateway startup auto-spawn conforms to the current worker-process decision;
  lazy desktop startup is a proposed change. The Windows orphan observed in the
  2026-07-18 live-process probes is an ownership failure not covered by the
  cited startup clause.
  `.vault/adr/2026-03-04-worker-process-architecture-adr.md:109-115`
- Edge conformance permits a `service_token` in discovery and an ungated health
  probe. Only Absent licenses start, but the gateway continues after a resident
  warning. Separately, the health contract expects `status == "ready"`, while
  top-level health emits `"ok"`.
  `.vault/adr/2026-07-14-a2a-edge-conformance-adr.md:280-291`
  `src/vaultspec_a2a/api/app.py:251-264`
  `src/vaultspec_a2a/api/app.py:425-456`
- Unauthenticated public reads and shutdown plus non-loopback binding are
  independently evidenced desktop security gaps not decided by those clauses.
- Missing Node adapter assets and a clean-wheel entry point that exits `3`
  conflict with dependency-hygiene and CLI-entry-point closure.
  `.vault/adr/2026-02-28-dependency-hygiene-cli-entry-point-adr.md:187`
  `.vault/adr/2026-02-28-dependency-hygiene-cli-entry-point-adr.md:358-360`
- Automatic migration startup depends on external Alembic configuration absent
  from the wheel, conflicting with the migration-framework packaging boundary.
  `.vault/adr/2026-03-31-database-migration-framework-adr.md:40-58`
