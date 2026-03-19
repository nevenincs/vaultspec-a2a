---
date: 2026-02-25
type: research
feature: web-app-architecture
description: 'Backend and frontend framework comparison covering FastAPI vs Starlette, React evaluation, state management strategies, and deployment model.'
name: 'Web App Architecture'
maturity: 30
summary: 'Backend and frontend framework comparison covering FastAPI vs Starlette, React evaluation, state management strategies, and deployment model.'
---

## Phase 3 Research: Web Application Architecture for Agent Team Gateway

**Date**: 2026-02-25
**Status**: Research
**Scope**: Backend framework, frontend framework, state management, deployment
model

---

## Part 1: Backend Framework -- FastAPI vs Starlette

### Architecture Relationship

FastAPI is built directly on top of Starlette. Every FastAPI WebSocket endpoint
uses Starlette's WebSocket class underneath. The performance characteristics are
therefore nearly identical -- any difference comes from FastAPI's dependency
injection and validation overhead, which is negligible for WebSocket endpoints
(validation only runs at connection time, not per-message).

### WebSocket Handling Patterns

### FastAPI Connection Manager Pattern

The standard pattern for managing multiple WebSocket clients in
FastAPI/Starlette
is the `ConnectionManager` class:

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, agent_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[agent_id] = websocket

    def disconnect(self, agent_id: str):
        self.active_connections.pop(agent_id, None)

    async def send_to(self, agent_id: str, data: dict):
        if ws := self.active_connections.get(agent_id):
            await ws.send_json(data)

    async def broadcast(self, data: dict):
        for ws in self.active_connections.values():
            await ws.send_json(data)
```text

This pattern works identically in both FastAPI and raw Starlette. The
`ConnectionManager`lives as application state shared via lifespan.

### Starlette Advantage: Lower-Level Control

Starlette exposes the raw ASGI interface, allowing custom WebSocket protocols,
binary frame handling, and subprotocol negotiation without any abstraction
overhead. For a terminal streaming use case (binary data from PTY), this
granularity matters.

### FastAPI Advantage: Dependency Injection

FastAPI's`Depends()` system works with WebSocket routes, enabling clean
authentication, session management, and shared state injection:

```python
@app.websocket("/ws/agent/{agent_id}")
async def agent_ws(websocket: WebSocket, agent_id: str, mgr: ConnectionManager = Depends(get_manager)):
    await mgr.connect(agent_id, websocket)
```text

### Concurrent Connection Performance

- Uvicorn handles WebSocket connections as asyncio tasks. Each connection is a
  coroutine -- not a thread -- so thousands of connections are feasible on a
  single process.
- Benchmarks show ~3,200 concurrent WebSocket connections on a single Uvicorn
  instance before degradation (vs 1,800 for Django Channels, 2,100 for
  Flask-SocketIO).
- For our use case (single-user, 5-20 agent terminals), connection limits are
  a non-issue.
- Uvicorn defaults: `--ws-max-size`16MB per message,`--ws-max-queue`32
  messages,`--ws-ping-interval`20s,`--ws-ping-timeout`20s.
- On Windows,`uvloop` is unavailable. Standard asyncio event loop is used,
  which is 2-4x slower than uvloop but still more than adequate for our scale.

### Serving REST + WebSocket from Same Application

Both FastAPI and Starlette natively support mixed HTTP/WebSocket routing on the
same application and port. No configuration or separate servers needed:

```python
app = FastAPI()

@app.get("/api/agents")          # REST endpoint
@app.websocket("/ws/events")     # WebSocket endpoint on same app
```text

Uvicorn handles the HTTP Upgrade handshake transparently.

### Lifespan Events for Process Supervision

Both frameworks use the same lifespan context manager pattern for managing
long-running background tasks (like agent process supervisors):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize process supervisor
    supervisor = AgentSupervisor()
    async with anyio.create_task_group() as tg:
        tg.start_soon(supervisor.run)
        app.state.supervisor = supervisor
        yield {"supervisor": supervisor}
        # Shutdown: cancel task group, cleanup
        supervisor.shutdown()
```text

Key considerations:

- `anyio.create_task_group()`provides structured concurrency for managing
  agent subprocesses.
- Starlette lifespan state is shared to requests via`request.state`.
- For subprocess management (spawning/monitoring agent processes), use
  `asyncio.create_subprocess_exec()`within the task group.
- Avoid`BackgroundTasks`for long-running process supervision -- it is designed
  for post-response cleanup, not persistent background work.

### Recommendation: FastAPI

**Choose FastAPI** for these reasons:

1. DI system simplifies WebSocket auth, session management, shared state.
2. REST API endpoints benefit from automatic OpenAPI docs, validation, typing.
3. Zero performance cost for WebSocket-heavy workloads (same Starlette core).
4. We need both REST (agent management CRUD) and WebSocket (event streaming).
5. Lifespan handling is identical to Starlette.
6. Larger ecosystem, more middleware, better documentation.

The "Starlette is lighter" argument is irrelevant here -- FastAPI adds ~zero
overhead for WebSocket paths, and we want the REST API features.

---

## Part 2: Frontend Framework Comparison

### React

### Architecture (as used by Open WebUI)

- Open WebUI uses React frontend + FastAPI backend (three-tier
  architecture).
- File-based routing with nested layouts for initialization (root layout handles
  WebSocket/auth/theming, app layout loads models/tools/settings).
- Frontend is compiled to a static SPA (HTML/CSS/JS) -- no runtime coupling to
  the backend. Backend serves these static assets alongside API endpoints. -`src/lib/`for reusable components, i18n, API logic, state management. -`src/routes/` for page definitions.

### React 5 Runes for Real-Time State

- React 5's runes (`$state`, `$derived`, `$effect`) provide signal-based
  fine-grained reactivity. Only the specific DOM nodes dependent on changed data
  re-render -- no virtual DOM diffing.
- This is ideal for high-frequency streaming updates (hundreds of events/sec)
  because updates to one agent's terminal do not trigger re-renders of other
  agents' panels.
- Compiler-optimized output produces smaller bundles and faster runtime than
  React's virtual DOM approach.
- Bundle size: 3-10KB for small apps (vs React's 40-100KB baseline).

### WebSocket Integration

- React is adding native WebSocket support (currently in testing).
- Current stable approach: plain WebSocket API in `onMount()`with React stores
  or runes for reactive state distribution.
- No framework-specific WebSocket abstraction needed -- vanilla JS WebSocket
  works naturally with React's reactivity.

### xterm.js Integration

-`xterm-React`is an actively maintained React wrapper for xterm.js.

- Handles addon management and stays current with both React and xterm.js
  releases.
- Clean component API:`<Xterm bind:terminal on:data={handleInput} />`.

**Verdict:** Best balance of performance, bundle size, and developer experience
for real-time dashboards. Open WebUI proves the React + FastAPI pattern
works
at scale.

### React / Next.js

### Architecture (as used by AutoGen Studio)

- AutoGen Studio uses React frontend (Gatsby-based) + FastAPI backend.
- WebSocket communication via `WorkflowManager`class wrapping agent
  interactions.
- State management via React hooks; streaming via WebSocket event handlers.

### State Management for Streaming

- React's virtual DOM is fundamentally at odds with high-frequency updates.
  Every state change triggers component re-rendering and DOM diffing.
- Workarounds:`useMemo`, `useCallback`, `React.memo`to prevent cascading
  re-renders -- significant complexity tax.
- Zustand is the modern choice for external state (simpler than Redux), but
  still suffers from React's reconciliation overhead for rapid updates.
- For terminal views receiving hundreds of lines/sec, React's rendering model
  is the wrong abstraction.

### xterm.js Integration: (2)

-`xterm-react`and`react-xtermjs` provide React wrappers.

- React's lifecycle management (useEffect cleanup, ref forwarding) adds
  complexity to xterm.js integration compared to React's simpler model.

**Bundle Size:** 40-100KB baseline (React + ReactDOM), plus router, state
management library. Typical app: 150-300KB.

**Verdict:** Viable but suboptimal. React's rendering model fights against our
core use case (high-frequency streaming updates). The ecosystem is large but
we pay for it in bundle size and complexity.

### HTMX + Alpine.js

### Architecture

- Server-rendered HTML with HTMX handling server-driven updates and Alpine.js
  for client-side interactivity (dropdowns, tabs, filters).
- Combined bundle: ~29KB (14KB HTMX + 15KB Alpine).
- No build step required.

### WebSocket/SSE Support

- HTMX has a WebSocket extension (`hx-ws`) for bidirectional communication.
- SSE support is native and more idiomatic for the HTMX model.
- Server pushes HTML fragments that HTMX swaps into the DOM.

### Limitations for Our Use Case

- Complex state synchronization between many interactive panels becomes
  unwieldy. Real-world reports cite "complex data flow and synchronization
  issues" with Alpine.js reactive variables in dashboard contexts.
- Form validation becomes unreliable; error handling is difficult with mixed
  HTML/JSON response types.
- **Critical limitation**: xterm.js requires a JavaScript-heavy integration
  (canvas rendering, WebGL addon, binary data handling). This fundamentally
  conflicts with HTMX's server-rendered-HTML paradigm. There is no HTMX-native
  way to embed xterm.js terminals.
- Multi-terminal views with independent state, resizing, scrollback buffers --
  this is exactly the kind of rich client-side state that HTMX is designed to
  avoid.

**Verdict:** Not suitable. HTMX excels at server-rendered CRUD apps but cannot
handle the client-side complexity of terminal emulators, code viewers, and
multi-panel real-time dashboards.

### Solid.js

### Architecture: (2)

- Fine-grained reactivity via signals (similar concept to React 5 runes).
- No virtual DOM -- updates the exact DOM nodes that depend on changed data.
- JSX syntax (React-like) but with fundamentally different rendering model.
- Bundle size: ~7KB baseline.

### Performance

- Lighthouse score: 98 (vs React 96, React ~85).
- Fastest runtime performance in JS framework benchmarks.
- Ideal for high-frequency DOM updates -- each signal change updates only
  its subscribers.

### Limitations

- Smallest ecosystem of all options. Limited component libraries.
- No xterm.js wrapper exists -- would need to build custom integration.
- SolidStart (SSR framework) is less mature than React or Next.js.
- Fewer developers familiar with it -- harder to find resources/help.

**Verdict:** Technically excellent for our performance needs but ecosystem
immaturity is a real cost. No xterm.js wrapper means building and maintaining
custom integration code.

### Frontend Recommendation: React

**Choose React (React 5)** for these reasons:

1. Fine-grained reactivity via runes handles high-frequency streaming without
   performance tricks.
2. Proven architecture: Open WebUI demonstrates React + FastAPI at scale.
3. `xterm-React`provides maintained xterm.js integration.
4. Smallest bundle size among full-featured frameworks (3-10KB baseline).
5. Compiles to static SPA -- trivial to serve from FastAPI backend.
6. Vite-based build tooling with fast HMR during development.
7. Growing ecosystem with good component library support (Skeleton,
   shadcn-React).

---

## Part 3: State Management Architecture

### Server-Authoritative State vs Optimistic Client State

For an agent dashboard, **server-authoritative state** is the correct model:

- Agent state is ground truth that lives on the server (process status, output
  buffers, task queues). The client is a view into this state.
- There is no "optimistic update" for terminal output -- you cannot predict what
  an agent will output next.
- User actions (start/stop agent, send message, approve permission) are commands
  sent to the server; the server applies them and streams results back.
- The only client-local state is UI state: which panel is selected, scroll
  position, layout preferences.

**Pattern:** Server pushes events via WebSocket. Client maintains a projection
of server state. All mutations go through the server.

### WebSocket Reconnection and State Recovery

### Reconnection Strategy

- Exponential backoff with jitter: start 1s, double each attempt, max 30s,
  random jitter to prevent thundering herd.
- Heartbeat/ping-pong to detect stale connections (Uvicorn provides this via
  `--ws-ping-interval`).

### State Recovery on Reconnect

This is the critical design challenge. Two approaches:

### Approach A: Event Replay with Sequence Numbers

- Server assigns monotonically increasing sequence numbers to all events.
- Client tracks last received sequence number.
- On reconnect, client sends last sequence number; server replays missed events.
- Pros: Simple, correct, no data loss.
- Cons: Requires server to buffer events (memory/disk), replay can be slow for
  long disconnections.

### Approach B: Snapshot + Live Stream (Recommended)

- On reconnect, server sends a full state snapshot (current agent statuses,
  recent terminal output, task states).
- Client replaces its entire state with the snapshot, then resumes live
  streaming.
- Pros: Fast reconnection regardless of disconnect duration, bounded server
  memory usage.
- Cons: Snapshot generation must be efficient; brief "flash" as UI rehydrates.

### Hybrid (Best)

- Server maintains a rolling event buffer (last N events per agent).
- On reconnect: if client's last sequence is within the buffer, replay from
  there. Otherwise, send full snapshot.
- This matches how Grafana Live works: in-memory subscription state with
  optional Redis persistence for multi-node, but for single-user local tool,
  in-memory is sufficient.

### Jupyter's Lesson

- Jupyter has struggled with state recovery across page reloads. A new session
  ID is generated on every page load, making reconnection to existing kernel
  sessions impossible without workarounds. Their kernel message replay system
  is based on session ID matching.
- We should avoid this: use a server-generated session ID that persists in
  `localStorage`, allowing reconnection to the same logical session.

### Event Sourcing for Agent Events

### Pattern

- All agent events (output lines, status changes, task updates, errors) are
  appended to an ordered event log.
- Current state is derived by replaying events (or maintained as a projection
  updated on each event).
- Event log enables: time-travel debugging, audit trail, state recovery after
  reconnect, historical analysis of agent runs.

### Implementation

```text
Event schema:
  - id: auto-increment integer
  - agent_id: string
  - event_type: enum (output, status_change, task_update, error, ...)
  - payload: JSON
  - timestamp: datetime
  - sequence: per-agent monotonic counter
```typescript

Events are written to SQLite (see below) and simultaneously broadcast to
connected WebSocket clients.

### SQLite as Embedded State Store

### For a single-user local dev tool, SQLite is the clear choice

| Factor             | SQLite                   | Redis                       | PostgreSQL              |
| ------------------ | ------------------------ | --------------------------- | ----------------------- |
| Installation       | Built into Python stdlib | Separate server process     | Separate server process |
| Zero-config        | Yes                      | No                          | No                      |
| Persistence        | Durable by default       | Requires config (RDB/AOF)   | Durable by default      |
| Single-user perf   | Excellent                | Overkill                    | Overkill                |
| Disk footprint     | Single file              | Separate process + data     | Separate process + data |
| Distribution model | `pip install`            | Docker/system package       | Docker/system package   |
| Async support      | `aiosqlite`              | `redis.asyncio`             | `asyncpg`               |
| Query capability   | Full SQL                 | Key-value + data structures | Full SQL                |

### SQLite advantages for our use case

- Zero external dependencies. Comes with Python.
- Single-file database simplifies backup, reset, and portability.
- WAL mode enables concurrent reads during writes (important for streaming
  events while querying history).
- For event volumes we expect (tens of thousands of events per session), SQLite
  handles this trivially. -`aiosqlite`provides async interface compatible with FastAPI's async handlers.

**When to consider Redis:** Only if we need pub/sub between multiple server
processes. For single-process, single-user tool, SQLite + in-memory state is
simpler and sufficient.

### Grafana's Approach (Reference)

- Grafana Live uses in-memory state for subscriptions with optional Redis
  backend for multi-node deployments.
- Single WebSocket per browser tab, multiplexing all subscriptions.
- Default limit: 100 WebSocket connections per Grafana instance.
- For single-node: in-memory is the default and recommended approach.
- This validates our architecture: in-memory state for live data, SQLite for
  persistence, single multiplexed WebSocket per client.

---

## Part 4: Deployment Model

### Option A:`pip install`+`uvicorn` (Recommended)

### Pattern (as used by Jupyter, Open WebUI)

```bash
pip install vaultspec-control-surface
# or: uv pip install vaultspec-control-surface
vaultspec-ui  # CLI entry point that starts uvicorn
```text

### How Open WebUI does it

- Published on PyPI as `open-webui`.
- React frontend is compiled to static assets and included in the Python
  package.
- Backend serves compiled frontend assets alongside API endpoints.
- `pip install open-webui`then`open-webui serve`starts everything.
- Minimal dependency set (~40 packages) available for lightweight deployments.

### Implementation: (2)

1. React app compiled with`vite build`producing`build/`directory of
   static assets (HTML, CSS, JS).
2. Static assets included in Python package via`pyproject.toml`package data.
3. FastAPI serves static files from the bundled directory:

```python
 app.mount("/", StaticFiles(directory=static_dir, html=True))
```text

1. CLI entry point starts uvicorn programmatically:

   ```python
   import uvicorn
   uvicorn.run("vaultspec.ui:app", host="127.0.0.1", port=8420)
   ```text

### Pros

- Familiar Python installation workflow.
- Works with `uv`, `pip`, `pipx`.
- Easy to develop: run frontend dev server + backend dev server separately.
- Version management via PyPI/standard Python packaging.
- No system-level dependencies beyond Python.

### Cons

- Requires Python installed on system (acceptable for our user base).
- Frontend build step during package creation (CI handles this).

### Option B: Single Binary (PyInstaller / Nuitka)

### PyInstaller

- Packages Python app + interpreter + dependencies into a single executable.
- Cross-platform (Windows, Linux, macOS).
- Produces large binaries (50-200MB+ depending on dependencies).
- Startup time: 2-10 seconds (unpacking to temp directory).
- Fragile: native dependencies, hidden imports, anti-virus false positives on
  Windows.

### Nuitka

- Compiles Python to C, then to native binary.
- Better runtime performance than PyInstaller.
- Even larger build times and complexity.
- Requires C compiler toolchain.

### shiv

- Creates self-contained Python zip apps (.pyz files).
- Requires Python on the target system (like pip install, but as a single file).
- Fastest of the "single file" options but still needs Python runtime.

**Verdict:** Single-binary distribution adds significant complexity (build
pipeline, platform-specific binaries, debugging opaque packaging issues) for
marginal user benefit. Our users already have Python installed. Not recommended
as primary distribution method; consider as future enhancement if needed.

### Option C: Docker

### Pattern (as used by Dify, Open WebUI)

```bash
docker run -p 8420:8420 vaultspec/control-surface
```text

### Pros: (2)

- Completely self-contained: Python, dependencies, everything.
- Reproducible across platforms.
- Easy to add supporting services (if needed later).

### Cons: (2)

- Requires Docker installed (heavier requirement than Python for dev tools).
- Adds latency to startup.
- Awkward for a local dev tool that needs to access local filesystems, spawn
  local processes, interact with local Git repos.
- Volume mounting complexity for accessing workspace files.

**Verdict:** Offer as an option but not the primary deployment method. The need
to interact with local filesystem and processes makes Docker awkward for our
core use case.

### Static Asset Bundling Strategy

### Vite (via React)

- React uses Vite as its build tool.
- `vite build`produces optimized, hashed static assets.
- Tree-shaking, code splitting, CSS extraction handled automatically.
- esbuild is used internally by Vite for dependency pre-bundling (fast).
- Output:`build/`directory with`index.html`, JS chunks, CSS, assets.

### Integration with Python package

- Build frontend during CI/CD or as a pre-build step.
- Include `build/`directory in Python package as package data.
- FastAPI`StaticFiles`mount serves the built assets.
- Vite generates a`.vite/manifest.json` that maps source files to built
  output -- useful if server needs to reference specific assets.

---

## Comparison Matrix

| Criterion               | FastAPI + React   | FastAPI + React   | Starlette + React | FastAPI + HTMX |
| ----------------------- | ----------------- | ----------------- | ----------------- | -------------- |
| **WebSocket perf**      | Excellent         | Excellent         | Excellent         | Good           |
| **REST API**            | Great (auto docs) | Great (auto docs) | Manual            | Great          |
| **Terminal (xterm.js)** | xterm-React       | xterm-react       | xterm-React       | Not viable     |
| **High-freq updates**   | Excellent (runes) | Poor (VDOM)       | Excellent (runes) | N/A            |
| **Bundle size**         | ~10-30KB          | ~150-300KB        | ~10-30KB          | ~29KB          |
| **Dev experience**      | Great             | Good              | Moderate          | Great (simple) |
| **Ecosystem**           | Good, growing     | Excellent         | Good, growing     | Limited        |
| **Deployment**          | pip install       | pip install       | pip install       | pip install    |
| **State recovery**      | Snapshot + replay | Snapshot + replay | Snapshot + replay | Server-side    |
| **Complexity**          | Moderate          | High              | Moderate          | Low            |

| Criterion             | SQLite    | Redis           | PostgreSQL |
| --------------------- | --------- | --------------- | ---------- |
| **Zero-config**       | Yes       | No              | No         |
| **Distribution**      | Built-in  | External        | External   |
| **Event persistence** | Good      | Requires config | Good       |
| **Async Python**      | aiosqlite | redis.asyncio   | asyncpg    |
| **Single-user perf**  | Excellent | Overkill        | Overkill   |

| Criterion              | pip install | Docker        | Single binary |
| ---------------------- | ----------- | ------------- | ------------- |
| **Install simplicity** | High        | Medium        | High          |
| **Prerequisites**      | Python      | Docker        | None          |
| **Local FS access**    | Native      | Volume mounts | Native        |
| **Update mechanism**   | pip upgrade | docker pull   | Download      |
| **Build complexity**   | Low         | Low           | High          |

---

## Final Recommendations

### Recommended Stack

| Layer               | Choice                      | Rationale                                                                         |
| ------------------- | --------------------------- | --------------------------------------------------------------------------------- |
| **Backend**         | **FastAPI**                 | DI, auto-docs, same Starlette WebSocket core                                      |
| **Frontend**        | **React (React 5)**         | Runes reactivity, xterm-React, proven with FastAPI (Open WebUI)                   |
| **State store**     | **SQLite** (via aiosqlite)  | Zero-config, built into Python, WAL mode for concurrent access                    |
| **Event transport** | **WebSocket** (not SSE)     | Need bidirectional: user sends commands, approves permissions, types in terminals |
| **Deployment**      | **`pip install` + uvicorn** | Follow Open WebUI/Jupyter model, include compiled React assets                    |
| **Build tooling**   | **Vite** (via React)        | Fast builds, tree-shaking, code splitting                                         |

### Architecture Summary

```text
User Browser
    |
    |--- WebSocket (multiplexed: events, terminal I/O, chat)
    |--- HTTP REST (agent CRUD, config, history queries)
    |
FastAPI (uvicorn)
    |
    |--- Static file serving (compiled React SPA)
    |--- WebSocket ConnectionManager (per-client multiplexed connection)
    |--- Agent Process Supervisor (lifespan task group)
    |--- Event Store (SQLite via aiosqlite, WAL mode)
    |
    |--- asyncio.create_subprocess_exec() for agent processes
```text

### Key Design Decisions

1. **Single multiplexed WebSocket per client** (like Grafana). Use message
   types/channels to route events to the correct UI component.

1. **Server-authoritative state** with snapshot-based recovery on reconnect.
   Client stores `lastSequence` in localStorage; server replays or snapshots
   based on gap size.

1. **Event sourcing to SQLite** for persistence. In-memory projections for
   live state. SQLite event log enables history, replay, and debugging.

1. **React compiled to static SPA** bundled in Python package. No Node.js
   runtime needed in production -- just Python + uvicorn.

1. **Lifespan-managed process supervisor** using anyio task groups for
   structured concurrency over agent subprocesses.

---

## Sources

### Part 1: Backend

- [FastAPI WebSocket Docs](https://fastapi.tiangolo.com/advanced/websockets/)
- [Starlette in 2026: Building Fast Async
  Services](https://thelinuxcode.com/python-starlette-in-2026-building-fast-async-services-with-clear-architecture/)
- [WebSocket Servers in Python with FastAPI or
  Starlette](https://teachmeidea.com/websocket-servers-in-python-with-fastapi-or-starlette/)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [Starlette Lifespan Docs](https://www.starlette.io/lifespan/)
- [Uvicorn Settings](https://www.uvicorn.org/settings/)
- [Realtime Channels with FastAPI +
  Broadcaster](https://dev.to/sangarshanan/realtime-channels-with-fastapi-broadcaster-47jh)

### Part 2: Frontend

- [Open WebUI Architecture
  (DeepWiki)](https://deepwiki.com/open-webui/open-webui/2-architecture)
- [Open WebUI Frontend Structure
  (DeepWiki)](https://deepwiki.com/open-webui/open-webui/2.1-frontend-structure)
- [Building a Real-time Dashboard with FastAPI and
  React](https://testdriven.io/blog/fastapi-React/)
- [xterm-react](https://github.com/PabloLION/xterm-react/)
- [SolidJS Creator on Fine-Grained
  Reactivity](https://thenewstack.io/solidjs-creator-on-fine-grained-reactivity-as-next-frontier/)
- [Frontend Framework Benchmarks
  2025](https://www.frontendtools.tech/blog/best-frontend-frameworks-2025-comparison)
- [HTMX + Alpine.js
  Combined](https://www.infoworld.com/article/3856520/htmx-and-alpine-js-how-to-combine-two-great-lean-front-ends.html)
- [AutoGen Agent Integration with FastAPI +
  WebSockets](https://newsletter.victordibia.com/p/integrating-autogen-agents-into-your)

### Part 3: State Management

- [WebSocket Reconnection Logic
  (2026)](https://oneuptime.com/blog/post/2026-01-27-websocket-reconnection/view)
- [WebSocket Architecture Best Practices
  (Ably)](https://ably.com/topic/websocket-architecture-best-practices)
- [Grafana Live
  Setup](https://grafana.com/docs/grafana/latest/setup-grafana/set-up-grafana-live/)
- [Jupyter Kernel State Recovery
  Proposal](https://github.com/jupyter-server/jupyter_server/issues/1274)
- [JupyterLab WebSocket
  Reconnection](https://github.com/jupyterlab/jupyterlab/pull/8432)
- [SQLite vs Redis Comparison
  (Airbyte)](https://airbyte.com/data-engineering-resources/sqlite-vs-redis)
- [SSE vs WebSocket Comparison](https://websocket.org/comparisons/sse/)
- [SSE Beat WebSockets for 95% of
  Apps](https://dev.to/polliog/server-sent-events-beat-websockets-for-95-of-real-time-apps-heres-why-a4l)

### Part 4: Deployment

- [Open WebUI on PyPI](https://pypi.org/project/open-webui/)
- [Open WebUI Installation Methods
  (DeepWiki)](https://deepwiki.com/open-webui/open-webui/3.1-installation-methods)
- [Open WebUI Build System
  (DeepWiki)](https://deepwiki.com/open-webui/open-webui/16.3-redis-integration-for-distribution)
- [Vite Backend Integration](https://vite.dev/guide/backend-integration)
- [PyInstaller vs Nuitka vs
  cx_Freeze](https://sparxeng.com/blog/software/python-standalone-executable-generators-pyinstaller-nuitka-cx-freeze)
- [Dify Docker Compose
  Deployment](https://docs.dify.ai/en/self-host/quick-start/docker-compose)
