---
adr_id: 009
title: Approved Module Hierarchy
date: 2026-02-25
status: Proposed
related:
  - docs/adrs/001-process-and-workspace-management.md
  - docs/adrs/004-event-aggregation-server-side-replay.md
  - docs/adrs/005-frontend-rendering-stack.md
  - docs/adrs/007-tech-stack-deployment.md
  - docs/research/2026-25-02-module-hierarchy-research.md
---

# ADR-009: Approved Module Hierarchy

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement
The A2A Orchestrator is a complex, multi-protocol system that bridges A2A, ACP, and MCP, manages native Windows processes, and serves a Svelte 5 frontend. To prevent architectural drift and "spaghetti bridging," we require a strictly defined module hierarchy that enforces separation of concerns between the backend (Python), the frontend (SvelteKit), and the various orchestration domains.

## 2. The Decision

We formalize the following repository and module structure:

### 2.1 Top-Level Topology
```text
vaultspec_a2a/
├── lib/                     # Backend Python package
└── ui/                      # Frontend SvelteKit project
```

### 2.2 Backend Module Hierarchy (`lib/`)
Organized by orchestration domain, isolating protocols from core logic.

```text
lib/
├── api/                 # FastAPI layer (ADR-007)
│   ├── auth.py          # WebSocket/REST authentication
│   ├── endpoints.py     # CLI bridge REST API
│   ├── schemas.py       # Pydantic models for frontend type-gen (Fix: Shared Schemas)
│   └── websocket.py     # WebSocket multiplexer (ADR-004)
├── core/                # Orchestration logic (ADR-001, ADR-008)
│   ├── aggregator.py    # Central Event Bus / Multiplexer (Fix: Event Aggregator)
│   ├── lifecycle.py     # Stability thresholds & health checks
│   ├── orchestrator.py  # Main engine
│   └── process_manager.py # Windows Job Objects & Process Supervision
├── database/            # Persistence (ADR-004, ADR-007)
│   ├── crud.py          # Event Sourcing / Task CRUD
│   ├── migrations/      # DB versioning
│   ├── models.py        # SQLAlchemy models
│   └── session.py       # DB session management
├── protocols/           # Protocol implementations (ADR-003, ADR-006)
│   ├── a2a/             # A2A logic & internal types
│   ├── acp/             # Ported patterns (Accumulator, Broker)
│   ├── adapter/         # ACP -> A2A translation layer ({{TRANS_LAYER}})
│   └── mcp/             # MCP server & elicitation queue
├── providers/           # Agent abstractions (ADR-002)
│   ├── base.py          # Provider interface
│   ├── claude.py        # Claude Code CLI wrapper
│   ├── gemini.py        # Gemini CLI wrapper
│   └── glm5.py          # GLM-5 OpenAI-compatible client
├── workspace/           # Filesystem isolation (ADR-001)
│   ├── env_resolver.py  # .venv path mapping for worktrees
│   └── git_manager.py   # Worktrees & Global Git Mutex
├── telemetry/           # Observability (Fix: OTel Integration)
│   └── instrumentation.py # OpenTelemetry spans & tracing
└── utils/               # Shared utilities
    ├── ansi_parser.py   # Raw ANSI -> Text for ring buffers
    ├── port_manager.py  # Port allocation logic ({{PORT_MANAGER}})
    └── decorators.py
```

### 2.3 Frontend Module Hierarchy (`ui/`)
Standard SvelteKit structure optimized for high-frequency streams.

```text
ui/src/lib/
├── components/          # ADR-005 components
│   ├── code_viewer/     # CodeMirror 6
│   ├── markdown/        # @humanspeak/svelte-markdown
│   ├── shadcn_ui/       # Tailwind v4 components
│   └── terminal/        # WebGL xterm.js
├── stores/              # Svelte 5 Runes
│   ├── agent_state.js   # Unified team status
│   └── permission_queue.js # Serialized user prompts
└── api/                 # Data fetching
    ├── websocket.js     # Backpressure-aware client ({{UI_ADAPTER}})
    └── rest.js          # Replay buffer fetchers
```

## 3. Rationale
*   **Domain Isolation:** Placing the Event Aggregator in `core/` ensures that protocol-specific modules (`protocols/`) only care about parsing, while the core logic handles the unified state.
*   **Type Safety:** The addition of `api/schemas.py` allows us to use tools like `openapi-typescript` to keep the Svelte frontend in sync with complex backend event payloads.
*   **Clean Replay:** By separating `ansi_parser.py`, we can maintain the 2000-line ring buffer (ADR-004) independently of the process management code.

## 4. Implementation Constraints
*   **Package Bundling:** The `ui/` build output must be targetable by `lib/api/` for static file serving during production deployment (ADR-007).
*   **Cross-Import Rules:** `protocols/` may import from `core/`, but `core/` should remain protocol-agnostic where possible, relying on the `adapter/` layer for data ingestion.

## 5. References

### 5.1 Local Research & Distilled Docs
- [Architecture Domain - Distilled](../distilled/2026-25-02-architecture-distilled.md)
- [Control Surface Gaps Research](../distilled/2026-25-02-control-surface-gaps-research.md)
- [Module Hierarchy Research](../research/2026-25-02-module-hierarchy-research.md)

### 5.2 Codebase Patterns
- **A2A Structure:** `knowledge/repositories/a2a-python/src/a2a/` (referenced for server/client split).
- **ACP Patterns:** `knowledge/repositories/acp-python-sdk/src/acp/contrib/` (referenced for `SessionAccumulator` placement).
- **FastAPI/Svelte Layout:** [jhundman/fastapi-sveltekit-template](https://github.com/jhundman/fastapi-sveltekit-template) (community best-practice reference).

### 5.3 Technical Fixes Incorporated
- **Event Aggregator:** Added `lib/core/aggregator.py`.
- **Telemetry:** Added `lib/telemetry/`.
- **Shared Schemas:** Added `lib/api/schemas.py`.
