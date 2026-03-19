---
adr_id: 007
title: Tech Stack & Deployment Strategy
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-architecture-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

## ADR-007: Tech Stack & Deployment Strategy

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The LangGraph orchestrator must manage highly concurrent, async-heavy
workloads (managing native LangGraph execution threads, multiplexing
WebSockets, parsing LangChain streams) while remaining simple to install and
run for end-users. It must provide both a REST API (for CLI tools) and a rich
real-time UI (Gateway) without requiring users to configure complex
infrastructure like Postgres, Redis, or Docker.

## 2. The Decision

We formalize the following technology stack and deployment architecture:

1. **Language:** **Python 3.13**. Utilizing modern typing and built-in async
   capabilities, managed strictly via the `uv` package manager.
2. **Backend Framework:** **FastAPI** running on **Uvicorn**. FastAPI will
   handle both the REST API (CLI bridging) and the WebSockets (UI streaming)
   on the same port.
3. **Persistence Layer:** **SQLite** accessed asynchronously via `aiosqlite`.
   The database will be strictly configured to use **WAL (Write-Ahead
   Logging) mode** to allow concurrent reads during high-frequency event
   sourcing writes.
4. **Frontend Delivery (Static SPA):** The React frontend will be compiled
   into a static Single Page Application (HTML/CSS/JS) via `vite build`.
5. **Deployment Model (`pip install`):** The compiled React static assets
   will be bundled directly into the Python package. In production, FastAPI
   will serve these files via `StaticFiles`. Users will install the entire
   system via `pip install vaultspec-orchestrator` (or `uv tool install`)
   and run a single command to start both the backend and the UI.

## 3. Rationale

- **FastAPI over raw Starlette:** While Starlette is the underlying engine
  for both, FastAPI provides a Dependency Injection (DI) system that
  drastically simplifies WebSocket authentication and shared state
  management. It also provides automatic OpenAPI documentation for the REST
  API at zero performance cost to the WebSocket channels.
- **SQLite WAL Mode:** An embedded, zero-config database is mandatory for a
  local developer tool. Standard SQLite locks the entire database during a
  write, which would bottleneck our Event Aggregator. WAL mode solves this by
  allowing concurrent readers while a write is occurring.
- **The "Jupyter" Deployment Pattern:** By compiling the React app to
  static files and serving them from Python, we completely eliminate the need
  for a Node.js runtime or complex Docker volume mounts on the user's
  machine. The user gets a full-stack web application from a simple Python
  package.

## 4. Rejected Alternatives

- **Raw Starlette:** Rejected. The "lightweight" argument is irrelevant
  because FastAPI adds no overhead to WebSocket paths, and we need the
  robust REST routing for the MCP/CLI bridge.
- **Postgres & Redis:** Rejected for v1. While powerful, they require
  external server processes, violating the requirement for a frictionless,
  zero-config local setup.
- **Docker as Primary Deployment:** Rejected. The orchestrator must directly
  manipulate local Git repositories and local filesystem workspaces
  seamlessly. Running the orchestrator inside a Docker container introduces
  severe volume-mounting friction for casual local users.

## 5. Implementation Constraints & Pitfalls

- **SQLite Connection Limits:** Even in WAL mode, `aiosqlite` can suffer from
  connection pool exhaustion if the Event Aggregator attempts to write
  thousands of concurrent events simultaneously. Writes must be batched or
  funneled through a single async worker.
- **Static Asset Caching:** When FastAPI serves the React `build/`
  directory, it must be configured with proper Cache-Control headers,
  otherwise, the browser will continuously re-download the JS bundles,
  degrading the initial load time of the Gateway.
- **Lifespan Management:** Long-running background tasks (like the Process
  Manager and Event Aggregator) must be carefully tied to FastAPI's
  `@asynccontextmanager` lifespan events using `anyio.create_task_group()`
  to ensure they start after the DB is ready and shut down cleanly before
  the server exits.

## 6. Negative Consequences

- **Vertical Scaling Limits:** Relying entirely on SQLite and in-memory
  application state restricts the orchestrator to a single-node deployment.
  If a future requirement demands distributed orchestration across multiple
  servers, the persistence layer must be migrated to Postgres/Redis.
- **Build Pipeline Complexity:** Developers must ensure the React build
  step (`npm run build`) correctly executes and outputs to the Python package
  directory before building the Python wheel, requiring a slightly more
  complex `pyproject.toml` or Makefile setup.

## 7. References

- [LangGraph Gap Audit Research](../research/2026-02-26-langgraph-gap-audit-research.md)
- [Architecture Domain - Distilled](../research/2026-02-25-architecture-distilled-research.md)

### 7.2 Codebase Modules & Patterns

- **Backend Framework:** `FastAPI` for REST APIs and WebSockets.
- **ASGI Server:** `Uvicorn` for running FastAPI applications.
- **Async Database Access:** `aiosqlite` for asynchronous SQLite interactions.
- **WAL Mode Configuration:** `PRAGMA journal_mode=WAL` for SQLite.
- **Static File Serving:** `fastapi.staticfiles.StaticFiles` for serving
  the React build.
- **Task Management:** `anyio.create_task_group` for managing background
  tasks during application lifespan.
- **Package Management:** `uv` (Hatchling/Rye equivalent) for Python
  dependency and environment management.
- **Frontend Build:** `vite build` (via React) for compiling static SPA assets.

### 7.3 Online Reference Implementation

- **FastAPI Documentation:** [FastAPI.tiangolo.com](https://fastapi.tiangolo.com/)
  (referenced for async endpoints, Dependency Injection, WebSockets, and
  `StaticFiles`).
- **Uvicorn Documentation:** [Uvicorn.org](https://www.uvicorn.org/)
  (referenced for ASGI server configuration).
- **aiosqlite GitHub:**
  [github.com/omnilib/aiosqlite](https://github.com/omnilib/aiosqlite)
  (referenced for asynchronous SQLite usage).
- **SQLite WAL Mode:**
  [SQLite.org WAL Documentation](https://www.sqlite.org/wal.html) (referenced
  for concurrent read/write benefits).
- **React Deployment:**
  [React.dev Deployment](https://react.dev/learn/start-a-new-react-project)
  (referenced for static site generation and build process).
- **uv Package Manager:** [astral.sh/uv](https://astral.sh/uv) (referenced
  for modern Python dependency management).
