---
tags:
- '#adr'
- '#approved-module-hierarchy'
date: 2026-02-26
modified: '2026-02-26'
related:
- '[[2026-02-26-process-and-workspace-management-adr]]'
- '[[2026-02-25-llm-context-provider-abstraction-adr]]'
- '[[2026-02-26-protocol-bridging-translation-adr]]'
- '[[2026-02-26-event-aggregation-server-side-replay-adr]]'
- '[[2026-02-26-tech-stack-deployment-adr]]'
- '[[2026-02-26-orchestration-topology-pipeline-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `approved-module-hierarchy` adr: `adr-009` | (**status:** `proposed`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-009`
- Original title: `Approved Module Hierarchy (LangGraph Core)`
- Legacy status at migration time: `Proposed`

## Original ADR

## ADR-009: Approved Module Hierarchy (LangGraph Core)

**Date:** 2026-02-26
**Status:** Proposed

## 1. Context & Problem Statement

The A2A Orchestrator bridges the A2A protocol, MCP, and now serves as a
host for a native **LangGraph** execution engine. To prevent architectural
drift, we require a strictly defined module hierarchy enforcing the
separation between the execution graphs, the frontend (React), and
external protocol bridges.

## 2. The Decision

We formalize the following repository and module structure.

### 2.1 Top-Level Topology

The Python package root is `lib/` (matching `pyproject.toml`'s
`packages = ["lib"]`). The frontend lives at `src/ui/`. All Python import
paths begin with `lib.*`.

```text
├── lib/                     # Backend Python package (import as lib.*)
│   └── (see §2.2)
└── src/
    └── ui/                  # Frontend React project (see §2.3)
```text

### 2.2 Backend Module Hierarchy (`lib/`)

Organized by orchestration domain, isolating protocols from the LangGraph
core. Each domain directory contains a `tests/` subdirectory for Rust-style
co-located unit tests (per GEMINI.md testing mandate).

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
├── core/                    # LangGraph Orchestration logic (ADR-008, LangGraph Audit)
│   ├── __init__.py
│   ├── aggregator.py        # Central Event Bus / Multiplexer (ADR-004)
│   ├── graph.py             # LangGraph StateGraph compilation (Nodes & Edges)
│   ├── nodes/               # Individual LangGraph execution nodes (Planner, Coder)
│   │   ├── __init__.py
│   │   ├── tools.py         # LangChain @tool definitions for agents
│   ├── state.py             # LangGraph State TypedDict & reducers
│   └── tests/
├── database/                # Persistence (ADR-004, ADR-007, LangGraph Checkpointing)
│   ├── __init__.py
│   ├── crud.py              # Event Sourcing / Task CRUD
│   ├── migrations/          # DB versioning
│   ├── models.py            # SQLAlchemy/Pydantic models
│   ├── session.py           # aiosqlite session, WAL, & langgraph SqliteSaver binding
│   └── tests/
├── protocols/               # Protocol implementations (ADR-003, ADR-006)
│   ├── __init__.py
│   ├── a2a/                 # A2A parsing & generic message wrapping
│   │   └── __init__.py
│   ├── mcp/                 # MCP server, tool surface & CLI bridge
│   │   ├── __init__.py
│   │   ├── server.py        # MCP tool surface: team/create, team/status
│   └── tests/
├── providers/               # LangChain BaseChatModel wrappers (ADR-002)
│   ├── __init__.py
│   ├── factory.py           # Instantiates ChatAnthropic, ChatGoogleGenerativeAI
│   └── tests/
├── workspace/               # Filesystem isolation (ADR-001)
│   ├── __init__.py
│   ├── git_manager.py       # Worktrees, merge strategy & Global Git Mutex
│   └── tests/
├── telemetry/               # Observability
│   ├── __init__.py
│   ├── instrumentation.py   # OpenTelemetry spans & LangSmith tracing
│   └── tests/
└── utils/                   # Shared utilities
    ├── __init__.py
    ├── enums.py             # Provider, Model, and other shared enums
    ├── logging.py           # Structured logging setup
    ├── printer.py           # Console output formatting
    └── tests/
```text

#### Key Architectural Shifts vs. Subprocess Hierarchy

| Old Module                | New approach in LangGraph Core                                                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `core/process_manager.py` | **DELETED.** Subprocesses are dead. Execution is native Python async functions inside LangGraph.                                                |
| `core/registry.py`        | **DELETED.** LangGraph's `checkpointer` manages session thread IDs and state intrinsically. No manual port-mapping registry needed.             |
| `core/permissions.py`     | **REFACTORED.** Permissions are managed via LangGraph's native `interrupt_before` node configurations rather than custom blocking queues.       |
| `providers/claude.py`     | **REFACTORED.** Subprocess CLI wrappers are dead. Replaced by `factory.py` dispensing `ChatAnthropic` and `ChatOpenAI` instances via LangChain. |
| `protocols/acp/`          | **DELETED.** The "ACP Richness Gap" is solved dynamically by intercepting LangChain tool-callbacks. We no longer need to parse raw ACP strings. |

### 2.3 Frontend Module Hierarchy (`src/ui/`)

Standard React structure optimized for high-frequency streams.

```text
ui/src/lib/
├── components/              # ADR-005 components
│   ├── code_viewer/         # CodeMirror 6 (read-only artifact inspector)
│   ├── diff/                # diff2html renderer
│   ├── markdown/            # @humanspeak/React-markdown (streaming)
│   ├── permission/          # Permission request modal (LangGraph interrupt consumer)
│   ├── shadcn_ui/           # Tailwind v4 primitives
│   └── terminal/            # WebGL xterm.js with backpressure
├── stores/                  # React 5 Runes state
│   ├── agent_state.React.ts    # Per-thread status, events, artifacts
│   ├── team_state.React.ts     # Aggregate team status
│   └── permission_queue.React.ts # Serialized user prompts
└── api/                     # Data fetching
    ├── websocket.ts         # Backpressure-aware multiplexed client
    └── rest.ts              # Terminal replay buffer & snapshot fetchers
```text

### 2.4 Test Structure

Unit tests are co-located per domain (Rust-style, per GEMINI.md):

```text
src/vaultspec_a2a/core/tests/test_graph.py
src/vaultspec_a2a/core/nodes/tests/test_tools.py
...
```python

All tests use `pytest` with real processes and network calls. No mocks,
patches, stubs, or skips.

## 3. Rationale

- **Graph Over Process:** Shifting strictly to LangGraph nodes prevents the
  orchestrator from being a massive, bespoke process juggling framework and
  instead leans on peer-reviewed, production-ready LangChain state machine
  primitives.
- **Provider Abstraction:** Injecting `ChatAnthropic` natively solves the
  crippling "CLI binary" Windows problem immediately.

## 4. Implementation Constraints

- **Async Strictness:** All node logic in `core/nodes/` must be `async def`
  and use `ainvoke()` to avoid blocking the main Uvicorn event loop.
- **State Typings:** The `state.py` TypedDict must serialize cleanly to
  SQLite via the checkpointer.

## 5. Facade Pattern & Public API Exposure

1. **Top-Level Independence**: Sub-modules in `lib/` (API, Core, Protocols,
   etc.) must be designed as independent units that are independently
   testable.
2. **Sub-Module Facades**: The `__init__.py` file of each sub-module must
   act as a facade.
3. **Strict `__all__` Mandate**: Every sub-sub-module must define a `__all__`
   list.
4. **Relative Internal Imports**: All imports _within_ the `lib/` package
   must use relative import syntax (e.g., `from ..api import schemas`).

## 6. References

- LangGraph Gap Audit Research
- Module Hierarchy Research
- `knowledge/repositories/langgraph`
