---
name: "UI Terminal Dashboard Survey"
date: 2026-25-02
type: research
summary: "Comparative survey of agent UIs, terminal-in-browser solutions, and real-time dashboard projects with star counts and tech stack recommendations."
maturity: 20
---

# Phase 7: Agent UI, Terminal-in-Browser, and Real-time Dashboard Survey

**Date**: 2026-02-25
**Type**: Research
**Feature**: coding-teams

---

## PART 1: Agent UI Projects

### 1. Open WebUI (formerly Ollama WebUI)

**GitHub**: https://github.com/open-webui/open-webui (~45k+ stars)

**Tech Stack**:
- **Frontend**: SvelteKit (migrated from earlier Svelte)
- **Backend**: Python FastAPI
- **Database**: SQLAlchemy with SQLite (default, with optional encryption), PostgreSQL
- **State Management**: Svelte stores
- **Real-time**: Socket.IO + Server-Sent Events (SSE) hybrid
- **Caching/PubSub**: Redis-backed WebSocket manager for scalability
- **Observability**: OpenTelemetry integration
- **Storage**: Local filesystem, S3, Google Cloud Storage, Azure Blob Storage

**Architecture**:
Three-tier architecture with clear frontend/backend separation:
1. **Connection Layer**: Socket.IO client managed in root layout
2. **Event Processing Layer**: Event handlers in Chat.svelte processing incoming stream chunks
3. **Display Layer**: ResponseMessage.svelte components rendering streaming content incrementally

**Streaming Implementation**:
- Uses a **hybrid SSE + WebSocket** approach
- SSE stream opens when `stream=True`, with heartbeats emitted while processing
- Backend responds via WebSocket, instructing frontend to send SSE request for direct connection
- Frontend forwards received SSE data back through WebSocket
- Chat events (replace, status, message) handled over WebSocket channel
- Plugin/function system can emit custom chat events

**Plugin System**:
- Plugin Market with community plugins
- Plugins are independent functional modules or integrated with agents
- Plugin Gateway is a backend service with Edge Function deployment
- Assistants automatically identify user input and route to suitable plugins

**Multi-Agent Handling**:
- Supports multiple model backends (Ollama, OpenAI-compatible APIs)
- RAG integration with 9 vector database options
- No native multi-agent conversation visualization -- designed primarily as a chat UI

**What We Can Learn**:
- The SSE + WebSocket hybrid is powerful: SSE for model streaming, WebSocket for chat events and control messages
- Redis-backed WebSocket manager pattern is essential for horizontal scaling
- SvelteKit + FastAPI is a proven pairing for AI UIs
- Socket.IO multiplexing keeps connection count manageable

**Limitations**:
- Primarily a chat interface, not a multi-agent orchestration UI
- No built-in agent-to-agent conversation visualization
- Plugin system is chat-oriented, not workflow-oriented

---

### 2. AutoGen Studio (Microsoft)

**GitHub**: https://github.com/microsoft/autogen (~42k+ stars for main repo)

**Tech Stack**:
- **Frontend**: React (Gatsby framework) + TailwindCSS
- **Backend**: Python (FastAPI-based API)
- **Database**: SQLModel (Pydantic + SQLAlchemy) -- supports SQLite, PostgreSQL, MySQL, Oracle, MSSQL
- **Agent Framework**: AutoGen AgentChat (high-level multi-agent API)
- **Configuration**: Declarative JSON-based agent/workflow specification

**Architecture**:
- Backend provides Web API, Python API, and CLI interfaces
- Frontend provides three high-level sections:
  1. **Build**: Drag-and-drop interface for agent workflow specification (skills, models, agents, workflows)
  2. **Playground**: Chat interface per session with history, "publish to gallery" capability
  3. **Gallery**: View of chat history from published sessions

**Multi-Agent Conversation Visualization**:
- Renders the "inner monologue" of agents during execution
- Displays message count exchanged between agents
- Shows cost tracking per task execution
- Session-based chat history with agent interaction logs
- Designed to "gradually include tools for visualizing, observing, and debugging agent behaviors"

**What We Can Learn**:
- Declarative JSON-based agent specification is powerful for UI-driven configuration
- The Build/Playground/Gallery separation is a clean UX pattern for agent development
- Inner monologue rendering gives visibility into agent reasoning
- SQLModel (Pydantic + SQLAlchemy) is a clean ORM choice for Python backends
- Session-based organization with publish-to-gallery is a good workflow pattern

**Limitations**:
- Gatsby is a heavy framework choice for what is essentially a dashboard
- Real-time streaming details are not well documented in the public architecture
- The 0.4 rewrite (Jan 2025) introduced breaking changes; architecture still stabilizing
- Now merging into "Microsoft Agent Framework" with Semantic Kernel

---

### 3. Dify

**GitHub**: https://github.com/langgenius/dify (~100k+ stars)

**Tech Stack**:
- **Frontend**: Next.js (React) with React Flow for visual workflow orchestration
- **Backend**: Python Flask
- **Database**: PostgreSQL (primary), Redis (caching + session management)
- **Task Queue**: Celery (distributed async task processing)
- **Deployment**: Docker Compose / Kubernetes
- **Reverse Proxy**: Nginx
- **License**: Apache 2.0 (with commercial licensing)

**Architecture**:
Microservices-oriented with three core components:
1. **LLM Orchestration**: Connect/switch between LLM providers
2. **Visual Studio**: Drag-and-drop workflow design (React Flow), agent training, RAG configuration
3. **Deployment Hub**: One-click deployment as APIs, chatbots, or internal tools

**Real-Time Execution Monitoring**:
- LLMOps monitoring: analyze application logs and performance over time
- Token usage statistics with separate input/output token tracking
- Asynchronous, non-blocking database write operations for performance
- Workflow execution engine upgraded for parallel branch execution
- Production data annotations for continuous improvement

**What We Can Learn**:
- React Flow is the go-to library for visual workflow/DAG editors
- Flask + Celery is a battle-tested pattern for async workflow execution
- Separate token tracking (input vs output) is important for cost management
- Non-blocking DB writes are critical for workflow execution performance
- The visual workflow canvas is essential for orchestration platforms

**Limitations**:
- Flask (not async-native) may limit real-time streaming performance vs FastAPI
- Heavy infrastructure requirements (PostgreSQL + Redis + Celery + Nginx)
- Enterprise features are behind commercial licensing

---

### 4. CrewAI Studio / Visualizer

**GitHub (Studio)**: https://github.com/strnad/CrewAI-Studio (community, Streamlit-based)
**GitHub (Visualizer)**: https://github.com/Eng-Elias/CrewAI-Visualizer (community, Next.js-based)
**Official**: Crew Studio is part of CrewAI Enterprise (not open source)

**Tech Stack (Visualizer)**:
- **Frontend**: Next.js + TypeScript
- **Backend**: Node.js with `node-calls-python` to execute Python code
- **Database**: PostgreSQL + Prisma ORM
- **API**: GraphQL
- **Agent Framework**: CrewAI Python package

**Tech Stack (Studio - Community)**:
- **Frontend/Backend**: Streamlit (Python)
- **Environment**: Supports Conda and virtual environments
- **No-code**: GUI for managing and running CrewAI agents

**Crew Execution Visualization**:
- Role-based agent design (roles, goals, tools per agent)
- Task management with dynamic agent assignment
- Sequential and hierarchical process execution modes
- Visual representation of crew structure and task flow

**What We Can Learn**:
- `node-calls-python` bridge pattern is interesting but fragile
- GraphQL is a good fit for complex agent relationship queries
- Streamlit is quick for prototyping but not production-grade for rich UIs
- The official enterprise version being closed-source shows the commercial value in visualization

**Limitations**:
- Community tools are not actively maintained at production quality
- The `node-calls-python` bridge adds complexity and potential failure points
- No real-time streaming of execution progress in the open-source versions
- Streamlit version is single-threaded and not suitable for concurrent users

---

### 5. LobeChat

**GitHub**: https://github.com/lobehub/lobe-chat (~55k+ stars estimated)

**Tech Stack**:
- **Frontend**: Next.js 16 + React 19
- **State Management**: Zustand
- **Data Fetching**: SWR (client-side), tRPC (end-to-end type-safe API)
- **Database**: Drizzle ORM + PostgreSQL
- **UI Components**: Ant Design + lobe-ui (custom AIGC component library)
- **Internationalization**: i18next
- **Architecture**: Monorepo (@lobechat/ namespace)

**Architecture Evolution (v2.0)**:
- Moved from SSR to full SPA (Single Page Application)
- Reason: RSC architecture caused high-frequency network round-trips even for lightweight interactions (conversation switching)
- Result: Better performance for interactive AI chat experiences

**Real-Time Patterns**:
- Streaming responses from LLM providers
- Plugin Gateway as Edge Function (POST /api/v1/runner)
- Automatic plugin identification and routing during conversations
- Real-time information retrieval via plugin system

**Plugin System**:
- Plugin Market for extensibility
- Plugins can be standalone or integrated with agents
- Agent Market for pre-configured agent profiles
- Plugins process real-time information (web search, etc.)

**What We Can Learn**:
- **Zustand** is preferred over Redux/MobX for AI chat state management (lightweight, simple)
- **tRPC** provides excellent end-to-end type safety for API communication
- **Drizzle ORM** is a modern, type-safe alternative to Prisma/SQLAlchemy
- Moving from SSR to SPA was a deliberate performance decision for interactive AI UIs
- Monorepo architecture scales well for complex AI platforms
- Edge Functions for plugin gateway reduce latency

**Limitations**:
- Primarily a chat interface, not an agent orchestration platform
- No multi-agent workflow visualization
- The v2.0 rewrite indicates architectural instability in earlier versions

---

### 6. Langflow

**GitHub**: https://github.com/langflow-ai/langflow (~100k stars)

**Tech Stack**:
- **Frontend**: React with React Flow (node-based visual editor)
- **Backend**: Python (FastAPI-based)
- **Execution**: Each component has a `build()` method executed sequentially
- **Export**: Flows are JSON, exportable/importable
- **Deployment**: REST API or MCP server
- **License**: Open source

**Architecture**:
- Drag-and-drop canvas with sidebar component palette
- Node-based workspace where connections replace boilerplate code
- Components are Python classes that can be customized
- Flows compile to LangChain/LangGraph execution graphs
- Playground panel shows execution results with step-by-step control

**Execution Visualization**:
- Interactive playground for immediate testing
- Step-by-step execution control
- Async/streaming response handling between nodes
- Data passing between nodes is managed by the execution engine

**What We Can Learn**:
- React Flow is the dominant library for visual flow editors in AI
- "Components as Python code" pattern gives full transparency
- JSON export of flows enables portability and version control
- The build() method pattern for component execution is clean and extensible
- MCP server deployment option is forward-thinking

**Limitations**:
- Version stability issues (v1.7.0 yanked due to critical bugs)
- Visual editor can become unwieldy for complex multi-agent workflows
- Execution visualization is basic (playground panel, not rich real-time dashboards)
- Primarily focused on LangChain ecosystem

---

### 7. Flowise

**GitHub**: https://github.com/FlowiseAI/Flowise (~15k+ stars)

**Tech Stack**:
- **Frontend**: React (with React Flow for node editor)
- **Backend**: Node.js + Express
- **Database**: SQLite (default), with support for others
- **Architecture**: Monorepo with separate packages

**Architecture**:
Three distinct visual builders:
1. **Assistant**: Beginner-friendly guided setup
2. **Chatflow**: Single-agent systems, chatbots, RAG, Graph RAG
3. **Agentflow**: Multi-agent orchestration with branching, looping, routing

**Comparison with Langflow**:
| Aspect | Langflow | Flowise |
|--------|----------|---------|
| Backend | Python (FastAPI) | Node.js (Express) |
| Customization | Full source access per component | Template-based |
| Performance | 23% faster on complex RAG workflows | Better at scaling multi-threaded queries |
| Strength | Quick prototyping, LangChain native | Enterprise features, templates, multi-agent |
| Skill Level | Assumes AI familiarity | Graduated complexity (Assistant/Chatflow/Agentflow) |

**What We Can Learn**:
- The graduated complexity model (Assistant -> Chatflow -> Agentflow) is excellent UX
- Node.js backend enables better WebSocket handling and concurrent connections
- Branching/looping/routing in Agentflow is the right abstraction for orchestration
- Template system accelerates user onboarding

**Limitations**:
- Fewer stars and smaller community than Langflow/Dify
- Node.js limits access to the Python AI ecosystem (requires bridging)
- Less source-level customization than Langflow

---

## PART 2: Terminal-in-Browser Projects

### 1. xterm.js

**GitHub**: https://github.com/xtermjs/xterm.js (~18k+ stars estimated)

**Tech Stack**:
- **Language**: TypeScript
- **Rendering**: Canvas/WebGL2
- **Protocol**: Supports full VT terminal emulation
- **Distribution**: npm (@xterm/xterm)

**Architecture**:
Three-layer architecture:
1. **Frontend (Browser)**: xterm.js handles character encoding, keystroke capture, ANSI escape code rendering
2. **WebSocket Transport**: Bidirectional real-time communication
3. **Backend PTY**: Process output fed into xterm.js, browser input passed to PTY via WebSocket

**Key Addons**:
- `@xterm/addon-attach`: WebSocket attachment for shell API communication
- `@xterm/addon-fit`: Auto-resize terminal to container
- `@xterm/addon-webgl`: GPU-accelerated rendering
- `@xterm/addon-search`: Text search within terminal buffer

**Real-World Usage**:
- VS Code (integrated terminal)
- Proxmox VE (container terminals)
- HashiCorp Nomad (remote task connections)
- JupyterLab, Theia IDE, code-server

**What's Reusable**:
- This is THE library for terminal-in-browser. Every other project in this section uses it.
- Addon architecture is extensible
- WebGL rendering handles high-throughput output
- Well-maintained, active development

**Limitations**:
- Pure frontend library -- requires backend PTY management separately
- No built-in WebSocket server or PTY spawning
- Addon ecosystem requires careful version management

---

### 2. Wetty

**GitHub**: https://github.com/butlerx/wetty

**Tech Stack**:
- **Frontend**: xterm.js
- **Backend**: Node.js
- **Protocol**: WebSocket (not Ajax like predecessors)
- **SSH**: Configurable SSH host, port, user
- **Authentication**: SSH-based (password, OAuth, LDAP configurable)

**Architecture**:
- Node.js server acts as WebSocket-to-SSH bridge
- Browser connects via WebSocket to Wetty server
- Wetty server opens SSH connection to target host
- Bidirectional relay between WebSocket and SSH streams

**Security Model**:
- MUST be behind HTTPS reverse proxy for production use
- Inherits SSH server authentication mechanisms
- Supports OAuth/LDAP integration for authentication
- Without TLS, all input (passwords, commands) is visible in transit

**What's Reusable**:
- The WebSocket-to-SSH bridge pattern is clean and well-proven
- Configuration model for SSH targets is straightforward
- Docker deployment is well-supported

**Limitations**:
- SSH-only -- cannot connect to arbitrary processes/PTYs
- No built-in TLS (requires reverse proxy)
- Single-purpose tool, not a library

---

### 3. ttyd

**GitHub**: https://github.com/tsl0922/ttyd (~8k+ stars)

**Tech Stack**:
- **Language**: C
- **Libraries**: libwebsockets + libuv
- **Frontend**: xterm.js (with CJK/IME support)
- **Rendering**: WebGL2
- **TLS**: OpenSSL-based SSL support
- **File Transfer**: ZMODEM integration (lrzsz)

**Architecture**:
- C-based server for maximum performance
- libwebsockets handles WebSocket protocol
- libuv provides cross-platform async I/O
- Spawns a new process per client connection (default)
- Can share single process with multiplexer (tmux/screen)
- Default port 7681

**Security Model**:
- Built-in basic authentication
- Built-in SSL/TLS support (no reverse proxy required)
- Read-only mode option
- Maximum client limit configuration
- Cross-platform: macOS, Linux, FreeBSD, OpenWrt, Windows

**What's Reusable**:
- Extremely lightweight and performant (C implementation)
- Built-in security features (auth + TLS) unlike most alternatives
- ZMODEM file transfer is a unique capability
- Windows support is valuable for our use case

**Limitations**:
- C codebase is harder to extend/customize
- New process per connection (no built-in multiplexing)
- Limited configuration API (primarily CLI flags)

---

### 4. code-server

**GitHub**: https://github.com/coder/code-server (~70k+ stars)

**Tech Stack**:
- **Core**: VS Code open-source core
- **Backend**: Node.js
- **Frontend**: VS Code's Electron-based UI adapted for browser
- **Protocol**: WebSocket for terminal, HTTP for file operations
- **Deployment**: Docker, Kubernetes, native install

**Terminal Architecture**:
- VS Code's multi-process architecture: frontend in one process, backend (extensions, terminal, debugging) in separate process
- Terminal backend uses node-pty for PTY management
- WebSocket connection between browser and backend for terminal I/O
- Browser refactoring (2019+) enabled the web-based working mode
- Each terminal instance gets its own PTY and WebSocket channel

**Security Model**:
- Password-based authentication (auto-generated or configured)
- HTTPS support via reverse proxy or built-in
- Extension sandboxing inherited from VS Code

**What's Reusable**:
- The multi-process architecture pattern (frontend/backend separation) is robust
- node-pty for PTY management is the standard Node.js approach
- VS Code's terminal implementation is the most battle-tested web terminal

**Limitations**:
- Massive codebase -- extracting just the terminal component is impractical
- Tied to VS Code's architecture and extension system
- Heavy resource usage for just terminal functionality

---

### 5. Theia IDE

**GitHub**: https://github.com/eclipse-theia/theia (~20k+ stars)

**Tech Stack**:
- **Language**: TypeScript (full stack)
- **Frontend**: Browser-based UI
- **Backend**: Node.js
- **Protocol**: JSON-RPC over WebSocket
- **Terminal**: Separate WebSocket connection per terminal instance
- **Extensions**: VS Code extension compatible + native Theia extensions
- **Architecture**: Modular, not a VS Code fork

**Terminal Architecture**:
- Each terminal gets its own WebSocket connection
- JSON-RPC protocol for structured communication
- Different WebSocket connections for different purposes (LSP, DAP, terminal, etc.)
- New terminal-manager extension (v1.67, Dec 2025) for managing multiple terminals in a single view
- Clean frontend/backend separation with Node.js backend

**What's Reusable**:
- **JSON-RPC over WebSocket** is an excellent protocol pattern for structured terminal communication
- Per-terminal WebSocket connections provide isolation
- Modular architecture allows extracting just the terminal component
- The terminal-manager pattern for multi-terminal management is directly relevant

**Limitations**:
- IDE-focused -- terminal is one component among many
- Heavier than dedicated terminal solutions
- Extension compatibility with VS Code is not 100%

---

### 6. GoTTY

**GitHub**: https://github.com/yudai/gotty (~19k+ stars, archived)
**Active Fork**: https://github.com/sorenisanerd/gotty

**Tech Stack**:
- **Language**: Go
- **Frontend**: xterm.js + hterm
- **Protocol**: WebSocket
- **Default Port**: 8080

**Architecture**:
- Go-based WebSocket server relaying TTY output to clients
- Bidirectional: forwards client input to TTY, sends TTY output to clients
- New process spawned per client connection (default)
- Terminal multiplexer integration for shared sessions (tmux/screen)
- Inspired by Wetty's approach but implemented in Go

**Security Model**:
- TLS/SSL encryption support
- Optional client certificate authentication
- Basic authentication support

**What's Reusable**:
- Go's goroutine model handles concurrent WebSocket connections efficiently
- Simple relay architecture is easy to understand and replicate
- The project inspired many similar tools

**Limitations**:
- Original repository is archived/unmaintained
- Active forks exist but with varying maintenance levels
- Go dependency means separate runtime from Python backend

---

### 7. JupyterLab Terminal

**GitHub**: Part of https://github.com/jupyterlab/jupyterlab

**Tech Stack**:
- **Frontend**: TypeScript (Lumino widgets, uses xterm.js)
- **Backend**: Python Tornado server
- **Protocol**: WebSocket with custom message serialization
- **Kernel Communication**: ZeroMQ (multiplexed into WebSocket)

**Terminal Architecture**:
- Python Tornado server manages terminal sessions and kernel processes
- ZeroMQ sockets (shell, iopub, stdin channels) multiplexed into single WebSocket
- Channel name encoded in WebSocket messages for demultiplexing
- Default protocol: offset-based binary message format (JSON header + binary buffers)
- Optional v1 protocol: structured JSON with header, parent_header, metadata, content
- Heartbeat mechanism for connection health

**Message Serialization**:
- Kernel messages serialized with offset numbers for position tracking
- UTF-8 encoded stringified JSON for message content
- Binary buffer support for rich output (images, etc.)

**What's Reusable**:
- **ZeroMQ-to-WebSocket bridging** pattern is excellent for multi-channel communication
- Channel multiplexing over single WebSocket reduces connection overhead
- The message serialization protocol with offset-based binary is efficient
- Python Tornado is proven for async WebSocket handling

**Limitations**:
- Tightly coupled to Jupyter ecosystem
- ZeroMQ adds infrastructure complexity
- Terminal is secondary to notebook functionality

---

## PART 3: Real-Time Dashboard Projects

### 1. Grafana

**GitHub**: https://github.com/grafana/grafana (~66k+ stars)

**Tech Stack**:
- **Frontend**: React + TypeScript
- **Backend**: Go
- **Real-time Engine**: Grafana Live (built-in, since v8.0)
- **Protocol**: WebSocket (Pub/Sub model)
- **Plugin System**: Streaming data plugins

**Real-Time Architecture (Grafana Live)**:
- **Pub/Sub model**: Frontend subscribes to channels, receives published data
- **All subscriptions multiplexed** into single WebSocket connection per page
- **In-memory PUB/SUB hub** by default for handling subscriptions
- **Data push**: Events sent to frontend as soon as they occur
- **Streaming plugins**: Deliver data frames to panels without UI polling

**Performance Optimization**:
- WebSocket output (Telegraf v1.19.0+) avoids HTTP middleware overhead per request
- Significant CPU reduction vs HTTP polling
- Streaming data frames directly to panel components

**Scalability Considerations**:
- Default in-memory mode: dashboard changes only broadcast to users on same server instance
- HA mode requires external PUB/SUB (Redis, NATS) for cross-instance delivery
- Streaming data only reaches clients connected to the receiving instance without external PUB/SUB

**What's Reusable**:
- **Single WebSocket with channel multiplexing** is the gold standard pattern
- **Pub/Sub model** cleanly separates data producers from UI consumers
- **Streaming data plugins** provide extensible real-time data sources
- **In-memory default with external PUB/SUB for HA** is a practical scaling strategy

**Limitations**:
- Go backend is a separate runtime from our Python stack
- Overkill for process monitoring (designed for metrics/observability)
- HA configuration adds significant complexity

---

### 2. Portainer

**GitHub**: https://github.com/portainer/portainer (~32k+ stars)

**Tech Stack**:
- **Frontend**: AngularJS (legacy) / React (migration in progress)
- **Backend**: Go
- **Agent**: Lightweight Go agent on each Docker host
- **Protocol**: WebSocket for interactive container operations

**Architecture**:
- **Portainer Server**: Core web interface + management logic (runs as container)
- **Portainer Agent**: Lightweight daemon on Docker hosts for remote management
- **WebSocket Endpoints**:
  - Container stdio attachment (attach to running container)
  - Container exec (execute commands in container)
  - Kubernetes pod exec

**Real-Time Patterns**:
- WebSocket for bidirectional container I/O (exec, logs, stdio)
- Real-time container status monitoring
- Real-time log streaming from containers
- Agent-to-server communication for multi-host management

**What's Reusable**:
- **Agent pattern** for managing remote processes is directly relevant
- WebSocket-based container exec maps well to our agent process management
- Multi-host management via lightweight agents
- Real-time log streaming pattern

**Limitations**:
- AngularJS legacy (migration ongoing)
- Docker/Kubernetes-specific, not general process management
- Go backend adds separate runtime

---

### 3. PM2 Web UI

**GitHub**: https://github.com/Unitech/pm2 (~42k+ stars)
**Community Web UI**: https://github.com/oxdev03/pm2.web

**Tech Stack (PM2 Core)**:
- **Language**: Node.js
- **Process Model**: Cluster mode with built-in load balancer
- **Metrics**: @pm2/io module for gathering metrics and exposing remote actions
- **Web Dashboard**: PM2 Plus (paid SaaS) or community alternatives

**Tech Stack (pm2.web - Community)**:
- **Purpose**: Web-based monitoring and management dashboard
- **Features**: Process monitoring, control, logs, server functions, access controls

**Architecture**:
- PM2 daemon manages processes (start, stop, restart, cluster mode)
- @pm2/io module instruments applications for metrics collection
- PM2 Plus provides real-time SaaS dashboard across multiple servers
- Community alternatives (pm2.web, pm2-gui) provide self-hosted dashboards
- IPC bus for inter-process communication

**What's Reusable**:
- **Process lifecycle management** patterns (start, stop, restart, reload without downtime)
- **Cluster mode** for load-balanced process management
- **@pm2/io instrumentation pattern** for application-level metrics
- **IPC bus** for process communication is relevant for agent coordination

**Limitations**:
- Node.js-specific process manager
- Best features (dashboard, alerting) require PM2 Plus (paid)
- Community web UIs are not actively maintained
- No built-in WebSocket streaming for logs

---

### 4. Supervisor

**GitHub**: https://github.com/Supervisor/supervisor

**Tech Stack**:
- **Language**: Python
- **Web Server**: Built-in HTTP server
- **API**: XML-RPC over HTTP/Unix domain socket
- **CLI**: supervisorctl (talks to daemon via socket)
- **Events**: Event-based notification system

**Architecture**:
- **supervisord**: Server daemon managing child processes
- **supervisorctl**: CLI client connecting via Unix domain socket or TCP
- **Web Interface**: Built-in HTTP server at configurable port (e.g., :9001)
- **XML-RPC API**: Programmatic control of supervisor and managed processes
- **Event System**: Emits events for state changes (supervisor, process, communication)

**Real-Time Capabilities**:
- Event types: supervisor state changes, process state changes, process communication events
- Event listeners can subscribe to specific event types
- Process communication events enable inter-process messaging
- Tail-f equivalent for process logs via API

**What's Reusable**:
- **Event-based process monitoring** is directly applicable
- **XML-RPC API** pattern (though we'd use JSON-RPC or REST instead)
- **Process state machine** (STARTING, RUNNING, BACKOFF, STOPPING, STOPPED, EXITED, FATAL)
- **Process group management** maps well to agent teams
- **Event listener pattern** for real-time notifications
- Pure Python, directly integrable

**Limitations**:
- Web UI is extremely basic (HTML tables, no JavaScript interactivity)
- XML-RPC is outdated (JSON-RPC or REST preferred)
- No WebSocket support (HTTP polling only)
- Single-host only (no multi-host agent management)
- No container awareness

---

## Cross-Cutting Analysis

### Dominant Technology Patterns

| Pattern | Projects Using It | Relevance |
|---------|-------------------|-----------|
| React Flow for visual editors | Dify, Langflow, Flowise | High -- if we build workflow visualization |
| xterm.js for terminals | All terminal projects, VS Code, Theia, JupyterLab | Critical -- this is the standard |
| WebSocket for real-time | All projects | Critical -- universal choice |
| SSE for LLM streaming | Open WebUI, Dify | High -- standard for LLM token streaming |
| Zustand for state | LobeChat | Medium -- lightweight alternative to Redux |
| React Flow + Python backend | Langflow, Dify | High -- common for AI workflow UIs |
| JSON-RPC over WebSocket | Theia | High -- structured protocol for multi-channel |
| Pub/Sub multiplexed WebSocket | Grafana | High -- scalable real-time pattern |
| Process state machine | Supervisor, PM2 | High -- maps to agent lifecycle |

### Recommended Tech Stack for Our Use Case

Based on this survey, the optimal stack for a coding agent orchestration UI would be:

**Frontend**:
- **SvelteKit** or **Next.js** (both proven in agent UIs; SvelteKit is lighter, Next.js has larger ecosystem)
- **xterm.js** for terminal embedding (non-negotiable -- it's the universal standard)
- **Zustand** or Svelte stores for state management
- React Flow if visual workflow editing is needed

**Real-Time Communication**:
- **WebSocket** with channel multiplexing (Grafana pattern) for control plane
- **SSE** for LLM token streaming (Open WebUI pattern)
- **JSON-RPC over WebSocket** for structured terminal/agent communication (Theia pattern)

**Backend**:
- **FastAPI** (Python, async-native, proven in Open WebUI, Langflow)
- **Redis** for PUB/SUB and session management (proven in Open WebUI, Dify)
- Process management inspired by Supervisor's state machine + PM2's lifecycle patterns

**Terminal Integration**:
- **xterm.js** (frontend) + custom WebSocket-to-PTY bridge (backend)
- Per-terminal WebSocket connections (Theia pattern)
- Or ttyd as an embedded terminal server (C, lightweight, Windows support)

### Key Architectural Decisions to Make

1. **SSE vs WebSocket for streaming**: Hybrid approach (Open WebUI) is most flexible
2. **Per-terminal WebSocket vs multiplexed**: Theia uses per-terminal for isolation; Grafana multiplexes for efficiency. For agent terminals, per-terminal is likely better (isolation between agents)
3. **Visual workflow editor**: Only if we need drag-and-drop agent orchestration (React Flow is standard)
4. **Process management**: Supervisor's event-based model is most Pythonic and directly integrable
5. **Multi-host**: Portainer's agent pattern is the right model if agents run on different hosts

### GitHub Star Summary

| Project | Stars | Category |
|---------|-------|----------|
| Dify | ~100k | Agent UI |
| Langflow | ~100k | Agent UI |
| LobeChat | ~55k | Agent UI |
| Open WebUI | ~45k+ | Agent UI |
| AutoGen | ~42k+ | Agent UI |
| Flowise | ~15k+ | Agent UI |
| code-server | ~70k | Terminal |
| Grafana | ~66k | Dashboard |
| Portainer | ~32k | Dashboard |
| PM2 | ~42k | Process Mgmt |
| GoTTY | ~19k | Terminal |
| Theia | ~20k | Terminal/IDE |
| xterm.js | ~18k+ | Terminal Lib |
| ttyd | ~8k+ | Terminal |
