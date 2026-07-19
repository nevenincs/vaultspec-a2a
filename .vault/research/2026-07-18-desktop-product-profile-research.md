---
tags:
  - '#research'
  - '#desktop-product-profile'
date: '2026-07-18'
modified: '2026-07-18'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-03-04-worker-process-architecture-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-02-28-dependency-hygiene-cli-entry-point-adr]]"
  - "[[2026-03-31-database-migration-framework-adr]]"
---

# `desktop-product-profile` research: `adopting a dashboard-managed desktop runtime`

This research asks which runtime, security, packaging, and lifecycle boundaries
allow Agent-to-Agent (A2A) to operate as a dashboard-managed desktop component
without weakening its server deployment. It combines directed Vaultspec discovery, source
inspection, and clean artifact and live process experiments at commit
`db7400a`.

## Findings

### Desktop and server have different deployment forces

The accepted service-lifecycle architecture decision record (ADR) makes
container-first Docker Compose the
production boundary and does not provide a desktop lifecycle.
`.vault/adr/2026-03-20-service-lifecycle-architecture-adr.md:62-112` Current
Compose sources define gateway, worker, and Jaeger, with PostgreSQL selected by
an overlay. `service/docker-compose.prod.yml:14-92`
`service/docker-compose.prod.postgres.yml:6-52`

Desktop has different offline, privilege, loopback, singleton, state, update,
and package-manager constraints. The evidence therefore favors a distinct
desktop production profile while preserving Compose as the server profile.
PostgreSQL and Jaeger remain server infrastructure, and VidaiMock remains a
certification dependency.

### The current wheel is not a runnable desktop artifact

A clean wheel installs but cannot start a file-backed gateway. The 2026-07-18
clean-wheel probe observed startup exiting with code 3. Source inspection traced
that failure to external
`alembic.ini` lookup while resource discovery derived `project_root` from the
installed module path. `src/vaultspec_a2a/database/migrate.py:22-43`
`src/vaultspec_a2a/control/config.py:26-31`
`src/vaultspec_a2a/control/config.py:104-110`

The built wheel contains 447 entries, including 191 test-related archive
entries, and omits repository assets required by the default provider. Claude
and Z.ai resolve `node_modules/@agentclientprotocol/claude-agent-acp` from a
checkout-like root at `src/vaultspec_a2a/providers/factory.py:22-37`. The absent
package-local binary path remains experimental at
`src/vaultspec_a2a/providers/factory.py:232-270`.

The evidence favors a target-specific immutable runtime that supplies CPython
3.13, the A2A package, migrations, presets, Node.js 22, and pinned Agent Client
Protocol (ACP) 0.59.0.
The ADR must decide its ownership, activation, and compatibility contract.

### Base dependencies invalidate the release matrix

`pyproject.toml:7-36` makes Torch and `vaultspec-rag` unconditional production
dependencies even though production A2A code imports neither.
Retrieval-augmented generation (RAG) instead launches through mutable `uvx` resolution at
`src/vaultspec_a2a/providers/_acp_mcp.py:32-59`.

Intel macOS cannot resolve the required Torch distribution for CPython 3.13.
On the inspected Windows environment, Torch occupies 2.74 GiB. The evidence
favors removing Torch and RAG from the desktop base closure and representing
RAG as a separate capability. The ADR must decide how profiles report its
absence without downloading dependencies at runtime.

### The gateway is the natural desktop lifecycle unit

The gateway already owns the database, checkpointer, event aggregation, worker
client, spawner, watchdog, discovery writer, and shutdown sequence at
`src/vaultspec_a2a/api/app.py:127-365`. The worker uses the same managed
interpreter and starts through a serialized spawner at
`src/vaultspec_a2a/control/worker_management.py:307-315` and `:406-480`.

The standalone Model Context Protocol (MCP) adapter is independently invokable
over standard input/output or streamable Hypertext Transfer Protocol (HTTP) at
`src/vaultspec_a2a/protocols/mcp/__main__.py:24-51`. Authoring builds a
run-scoped server specification at
`src/vaultspec_a2a/providers/_acp_authoring.py:247-303`; ACP process creation and
tree cleanup occur per model invocation at
`src/vaultspec_a2a/providers/acp_chat_model.py:382-461` and `:530-578`. These
boundaries favor dashboard ownership of the gateway only, with the gateway
retaining worker and owned child-process authority.

Boot reconciliation currently calls `ensure_worker` before checking for work at
`src/vaultspec_a2a/control/dispatch.py:221-225`. Live shutdown also orphaned a worker
on Windows. The ADR must settle lazy startup, descendant containment, drain, and
owned shutdown behavior.

### Current network and discovery behavior is unsafe for desktop control

The default gateway binds to `0.0.0.0` at
`src/vaultspec_a2a/control/config.py:222-244`. `/v1` has no authentication
dependency at `src/vaultspec_a2a/api/routes/gateway.py:71`, and administrative
shutdown is unauthenticated at `src/vaultspec_a2a/api/routes/admin.py:5-14`.

Discovery publishes the internal gateway-worker token. Concurrent gateways
sharing one home start successfully and alternate overwriting the discovery
record. The warning-only path appears at `src/vaultspec_a2a/api/app.py:251-266`.

The evidence favors loopback binding, distinct dashboard-control and worker
interprocess communication (IPC) credentials, and an operating-system singleton held before discovery
publication. The ADR must settle the authenticated attachment record and the
rules for compatible foreign instances.

### Readiness currently conflates gateway and worker state

Live testing produced a gateway whose `/health` response reported ready while
`/v1/service` reported degraded because no worker answered. The two derivations
live at `src/vaultspec_a2a/api/app.py:425-456` and
`src/vaultspec_a2a/control/health.py:229-326`.

Provider-profile readiness already separates command and credential
availability at `src/vaultspec_a2a/providers/model_profiles.py:320-425`. The
evidence favors separate liveness, gateway readiness, worker state, and provider
eligibility. The ADR must decide whether a cold but startable worker is a healthy
desktop state.

### Mutable state and immutable runtime need separate authorities

A2A home already lives outside the repository, but database and workspace
defaults still depend on launch context at
`src/vaultspec_a2a/control/config.py:29-31`, `:69-76`, and `:103`.
Automatic startup migration has no product receipt or pre-migration backup.

SQLite snapshot and restore primitives exist at
`src/vaultspec_a2a/control/db.py:104-188`. The evidence favors explicit paths
for data, checkpoints, logs, discovery, credentials, receipts, temporary
provider homes, and workspaces. It also favors versioned immutable runtime
generations with update transactions that drain, snapshot, verify, migrate,
activate, probe, and roll back. The ADR must define which operations are legal
only for an owned installation.

### Alternatives carry clear knockout conditions

System Python and runtime package downloads cannot prove offline closure.
Docker Desktop adds an external runtime and a separate lifecycle. Python
freezers require replacing current `sys.executable -c` and
`sys.executable -m` child contracts. An embedded Rust payload preserves
binary-only channels but couples Rust and A2A replacement and rollback.

An adjacent opaque capsule preserves the interpreter contract and independent
component identity. Node.js matches the current provider path. Bun compilation
may reduce size later, but it has not proved platform-specific ACP resources on
all five targets. The ADR must choose between these options and record the
channel consequences.

### Acceptance requires real product evidence

Existing service tests start from the checkout interpreter and inject a project
root. They do not prove a built product capsule. A desktop profile needs real
clean and offline install, relocation, default-provider, singleton, authenticated
control, lazy-worker, descendant cleanup, tamper, update, rollback, repair,
remove, and package-channel tests.

Mocks, fakes, stubs, patches, monkeypatches, `skip`, and `xfail` cannot establish
these operating-system and packaging properties.

## Sources

- A2A runtime and packaging source at commit `db7400a`
- `src/vaultspec_a2a/api/app.py:127-456`
- `src/vaultspec_a2a/api/routes/gateway.py:71`
- `src/vaultspec_a2a/api/routes/admin.py:5-14`
- `src/vaultspec_a2a/control/config.py:29-31`
- `src/vaultspec_a2a/control/config.py:69-76`
- `src/vaultspec_a2a/control/config.py:103`
- `src/vaultspec_a2a/control/config.py:222-288`
- `src/vaultspec_a2a/control/db.py:104-188`
- `src/vaultspec_a2a/control/dispatch.py:221-225`
- `src/vaultspec_a2a/control/worker_management.py:307-519`
- `src/vaultspec_a2a/database/migrate.py:22-43`
- `src/vaultspec_a2a/providers/_acp_authoring.py:247-303`
- `src/vaultspec_a2a/providers/acp_chat_model.py:382-461`
- `src/vaultspec_a2a/providers/acp_chat_model.py:530-578`
- `src/vaultspec_a2a/providers/_acp_mcp.py:32-59`
- `src/vaultspec_a2a/providers/factory.py:22-37`
- `src/vaultspec_a2a/providers/factory.py:232-270`
- `src/vaultspec_a2a/providers/model_profiles.py:320-425`
- `src/vaultspec_a2a/protocols/mcp/__main__.py:24-51`
- `service/docker-compose.prod.yml:14-92`
- `service/docker-compose.prod.postgres.yml:6-52`
- `pyproject.toml:1-40`
- `package.json:7`
- Cargo Dist 0.32 configuration:
  https://github.com/axodotdev/cargo-dist/blob/v0.32.0/book/src/reference/config.md
- uv managed Python distributions: https://docs.astral.sh/uv/concepts/python-versions/
- python-build-standalone distribution model:
  https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html
- Bun standalone executable behavior: https://bun.sh/docs/bundler/executables
