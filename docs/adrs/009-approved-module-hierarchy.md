---
adr_id: 009
title: Approved Module Hierarchy
date: 2026-02-26
status: Proposed
related:
  - docs/adrs/001-process-and-workspace-management.md
  - docs/adrs/002-llm-context-provider-abstraction.md
  - docs/adrs/003-protocol-bridging-translation.md
  - docs/adrs/004-event-aggregation-server-side-replay.md
  - docs/adrs/005-frontend-rendering-stack.md
  - docs/adrs/007-tech-stack-deployment.md
  - docs/adrs/008-orchestration-topology-pipeline.md
  - docs/research/2026-25-02-module-hierarchy-research.md
---

# ADR-009: Approved Module Hierarchy

**Date:** 2026-02-26
**Status:** Proposed

## 1. Context & Problem Statement

The A2A Orchestrator is a complex, multi-protocol system that bridges A2A, ACP,
and MCP, manages native Windows processes, and serves a Svelte 5 frontend. To
prevent architectural drift and "spaghetti bridging," we require a strictly
defined module hierarchy that enforces separation of concerns between the
backend (Python), the frontend (SvelteKit), and the various orchestration
domains.

## 2. The Decision

We formalize the following repository and module structure.

### 2.1 Top-Level Topology

The Python package root is `lib/` (matching `pyproject.toml`'s
`packages = ["lib"]`). The frontend lives at `src/ui/`. All Python
import paths begin with `lib.*` — the `src/vaultspec_a2a/` directory has been removed.

```text
├── lib/                     # Backend Python package (import as lib.*)
│   └── (see §2.2)
└── src/
    └── ui/                  # Frontend SvelteKit project (see §2.3)
```

### 2.2 Backend Module Hierarchy (`lib/`)

Organized by orchestration domain, isolating protocols from core logic. Each
domain directory contains a `tests/` subdirectory for Rust-style co-located
unit tests (per GEMINI.md testing mandate).

```text
lib/
├── __init__.py
├── api/                     # FastAPI layer (ADR-007)
│   ├── __init__.py
│   ├── auth.py              # WebSocket/REST authentication
│   ├── endpoints.py         # CLI bridge REST API
│   ├── schemas.py           # Pydantic models for frontend type-gen
│   ├── websocket.py         # WebSocket multiplexer & message routing (ADR-004)
│   └── tests/
├── core/                    # Orchestration logic (ADR-001, ADR-002, ADR-008)
│   ├── __init__.py
│   ├── aggregator.py        # Central Event Bus / Multiplexer (ADR-004)
│   ├── lifecycle.py         # Stability thresholds & health checks (ADR-001 §2.2)
│   ├── orchestrator.py      # Main engine — team workflow & agent dispatch
│   ├── permissions.py       # Runtime permission policy engine (ADR-006 §4.2)
│   ├── process_manager.py   # Windows Job Objects & Process Supervision (ADR-001)
│   ├── registry.py          # Agent Registry: id→port→pid→state→card mapping
│   ├── state.py             # TeamState TypedDict, serialization & handoff (ADR-002)
│   └── tests/
├── database/                # Persistence (ADR-004, ADR-007)
│   ├── __init__.py
│   ├── crud.py              # Event Sourcing / Task CRUD
│   ├── migrations/          # DB versioning
│   ├── models.py            # SQLAlchemy/Pydantic models
│   ├── session.py           # aiosqlite session & WAL configuration
│   └── tests/
├── protocols/               # Protocol implementations (ADR-003, ADR-006)
│   ├── __init__.py
│   ├── a2a/                 # A2A client/server logic & internal types
│   │   └── __init__.py
│   ├── acp/                 # Ported ACP patterns (SessionAccumulator, PermissionBroker)
│   │   └── __init__.py
│   ├── adapter/             # ACP → A2A translation layer
│   │   └── __init__.py
│   ├── mcp/                 # MCP server, tool surface & elicitation queue
│   │   ├── __init__.py
│   │   ├── server.py        # MCP tool surface: team/create, team/status, etc.
│   │   └── elicitation.py   # asyncio.Queue elicitation serializer (ADR-003 §2.2)
│   └── tests/
├── providers/               # Agent provider abstractions (ADR-002)
│   ├── __init__.py
│   ├── base.py              # Provider interface / protocol
│   ├── claude.py            # Claude Code via claude-code-acp wrapper (ADR-006)
│   ├── gemini.py            # Gemini CLI wrapper
│   ├── glm5.py              # GLM-5 OpenAI-compatible client
│   └── tests/
├── workspace/               # Filesystem isolation (ADR-001)
│   ├── __init__.py
│   ├── env_resolver.py      # .venv path mapping for flat & worktree modes
│   ├── git_manager.py       # Worktrees, merge strategy & Global Git Mutex
│   └── tests/
├── telemetry/               # Observability
│   ├── __init__.py
│   ├── instrumentation.py   # OpenTelemetry spans & tracing
│   └── tests/
└── utils/                   # Shared utilities
    ├── __init__.py
    ├── ansi_buffer.py       # 2000-line ANSI ring buffer (ADR-004)
    ├── port_allocator.py    # Race-condition-proof port allocation
    ├── decorators.py
    └── tests/
```

#### Key additions vs. prior revision

| Module | ADR Source | Purpose |
| --- | --- | --- |
| `core/permissions.py` | ADR-006 §4.2, Process Distilled §4 | Runtime policy engine: per-agent mode, per-tool allow/deny, per-directory scope. Distinct from ACP `PermissionBroker` port which handles the blocking RPC. |
| `core/registry.py` | Architecture Distilled §3.3 | Agent `id→{port, pid, state, agent_card}` mapping. Thin, but avoids burying registry logic inside `orchestrator.py`. |
| `core/state.py` | ADR-002 §2.3–2.4, Arch Gaps §1 | `TeamState` TypedDict, JSON serialization, and A2A ContextId handoff logic. |
| `protocols/mcp/elicitation.py` | ADR-003 §2.2, Protocol Gaps §2 | `asyncio.Queue`-based serializer for concurrent `INPUT_REQUIRED`/`AUTH_REQUIRED` requests. |
| `*/tests/` directories | GEMINI.md Testing Setup | Co-located unit tests per domain. Global integration tests remain in top-level `tests/`. |

#### Renamed files vs. prior revision

| Old Name | New Name | Reason |
| --- | --- | --- |
| `utils/ansi_parser.py` | `utils/ansi_buffer.py` | Reflects primary role: maintaining the 2000-line ring buffer, not just parsing. |
| `utils/port_manager.py` | `utils/port_allocator.py` | Avoids confusion with `core/process_manager.py`. |

### 2.3 Frontend Module Hierarchy (`src/ui/`)

Standard SvelteKit structure optimized for high-frequency streams.

```text
ui/src/lib/
├── components/              # ADR-005 components
│   ├── code_viewer/         # CodeMirror 6 (read-only artifact inspector)
│   ├── diff/                # diff2html renderer
│   ├── markdown/            # @humanspeak/svelte-markdown (streaming)
│   ├── permission/          # Permission request modal
│   ├── shadcn_ui/           # Tailwind v4 primitives
│   └── terminal/            # WebGL xterm.js with backpressure
├── stores/                  # Svelte 5 Runes state
│   ├── agent_state.svelte.ts    # Per-agent status, events, artifacts
│   ├── team_state.svelte.ts     # Aggregate team status
│   └── permission_queue.svelte.ts # Serialized user prompts
└── api/                     # Data fetching
    ├── websocket.ts         # Backpressure-aware multiplexed client
    └── rest.ts              # Terminal replay buffer & snapshot fetchers
```

#### Additions vs. prior revision

- `components/diff/` — diff2html was mentioned in ADR-005/distilled but had no
  home in the hierarchy.
- `components/permission/` — Permission modal UI component was described in
  Architecture Distilled §6.4 but missing from the tree.
- `stores/team_state.svelte.ts` — Aggregate team status (used by MCP bridge
  status aggregation, ADR-003).
- File extensions changed from `.js` to `.svelte.ts` / `.ts` to match Svelte 5
  Runes and TypeScript-first architecture.

### 2.4 Test Structure

Unit tests are co-located per domain (Rust-style, per GEMINI.md):

```text
lib/core/tests/test_process_manager.py
lib/core/tests/test_lifecycle.py
lib/protocols/tests/test_elicitation.py
...
```

Integration tests that exercise multiple modules live at the repository root:

```text
tests/
├── conftest.py
├── test_e2e_agent_lifecycle.py
└── test_e2e_protocol_bridge.py
```

All tests use `pytest` with real processes and network calls. No mocks, patches,
stubs, or skips.

## 3. Rationale

- **Domain Isolation:** Placing the Event Aggregator in `core/` ensures that
  protocol-specific modules (`protocols/`) only care about parsing, while the
  core logic handles the unified state.
- **Type Safety:** `api/schemas.py` allows tools like `openapi-typescript` to
  keep the Svelte frontend in sync with backend event payloads.
- **Clean Replay:** Separating `ansi_buffer.py` maintains the 2000-line ring
  buffer (ADR-004) independently of the process management code.
- **Explicit Permission Split:** `core/permissions.py` (policy engine: "should
  this tool call be auto-approved?") is distinct from `protocols/acp/`
  (PermissionBroker port: "block the agent and ask the user"). Policy lives in
  core; the blocking RPC pattern lives in protocols.
- **Registry Extraction:** A dedicated `core/registry.py` prevents the
  orchestrator from becoming a monolith. The registry is a dependency of both
  `process_manager.py` and `aggregator.py`, making extraction natural.

## 4. Implementation Constraints

- **Package Path:** The Python package is `lib/`. Import paths
  are `lib.core.orchestrator`, `lib.api.endpoints`, etc.
  There is no `vaultspec_a2a` or `src` prefix in imports.
- **Package Bundling:** `src/ui/` build output targets `lib/static/`
  for static file serving during production deployment (ADR-007).
- **Cross-Import Rules:** `protocols/` may import from `core/`, but `core/`
  must remain protocol-agnostic where possible, relying on `protocols/adapter/`
  for data ingestion.
- **Test Co-location:** Each domain's `tests/` directory must contain a
  `conftest.py` for domain-specific fixtures.

## 5. Strict Boundaries to Prevent Drift & Spaghetti Coupling

- **ACP Transport Ban:** The `agent-client-protocol` package is a necessary
  dependency for its `SessionAccumulator` and `PermissionBroker` type
  primitives. However, its transport layer (especially `stdio`) is strictly
  **FORBIDDEN** to import or use. The system exclusively relies on the generic
  A2A server transport.
- **Subprocess Isolation:** To prevent coupling, the code executed inside an
  Agent Subprocess (the A2A server) is completely banned from importing from
  `lib.core.*` or `lib.providers.*`. The `lib/providers/` logic is exclusively
  for the parent orchestrator to spawn and manage wrappers, not for the agent
  to run inside itself. The agent subprocess is strictly a generic A2A-RPC
  server interface boundary.
- **Telemetry elevated to v1**: To avoid a blind deployment given the complexity
  of process management and distributed async behavior, the OpenTelemetry
  tracking component in `lib/telemetry/` is an explicit Version 1 requirement,
  overriding any earlier deferred classifications in preliminary assessments.

## 6. Facade Pattern & Public API Exposure

To ensure that the module hierarchy remains maintainable while providing a
clean interface for consumers, the following rules apply:

1. **Top-Level Independence**: Sub-modules in `lib/` (API, Core, Protocols,
    etc.) must be designed as independent units that are independently testable.
2. **Sub-Module Facades**: The `__init__.py` file of each sub-module (e.g.,
    `lib/core/__init__.py`) must act as a facade. It should explicitly import
    the public types, classes, and functions from its sub-sub-modules and
    expose them.
3. **Strict `__all__` Mandate**: Every sub-sub-module (e.g.,
    `lib/core/registry.py`) must define a `__all__` list containing its
    public exportable APIs.
4. **Relative Internal Imports**: All imports *within* the `lib/` package
    must use relative import syntax (e.g., `from ..api import schemas`).
    Absolute imports are reserved for external dependencies (e.g.,
    `import fastapi`).
5. **Consumable Root**: External modules should import from the sub-module
    root (e.g., `from lib.core import Registry`) whenever possible. Direct
    imports from deep sub-modules (e.g., `lib.core.registry.Registry`) are
    discouraged except where circular dependencies necessitate it.

## 5. References

### 5.1 Local Research & Distilled Docs

- [Architecture Domain - Distilled](../distilled/2026-25-02-architecture-distilled.md)
- [Process Domain - Distilled](../distilled/2026-25-02-process-distilled.md)
- [Control Surface Gaps Research](../distilled/2026-25-02-control-surface-gaps-research.md)
- [Module Hierarchy Research](../research/2026-25-02-module-hierarchy-research.md)

### 5.2 Codebase Patterns

- **A2A Structure:** `knowledge/repositories/a2a-python/src/a2a/` (server/client
  split).
- **ACP Patterns:** `knowledge/repositories/acp-python-sdk/src/acp/contrib/`
  (SessionAccumulator placement).

### 5.3 Technical Fixes Incorporated

- **Event Aggregator:** `core/aggregator.py` (prior revision fix).
- **Telemetry:** `telemetry/instrumentation.py` (prior revision fix).
- **Shared Schemas:** `api/schemas.py` (prior revision fix).
- **Elicitation Serializer:** `protocols/mcp/elicitation.py` (this revision).
- **Permission Engine:** `core/permissions.py` (this revision).
- **Agent Registry:** `core/registry.py` (this revision).
- **Team State:** `core/state.py` (this revision).
- **Test Structure:** `*/tests/` directories (this revision).
