# Module Hierarchy Research

**Date**: 2026-02-25
**Summary**: Analysis of repository structures from A2A, ACP, and Toad to inform the `vaultspec-a2a` module design.

---

## 1. Key Repository Insights

### 1.1 A2A Python SDK (`a2a-python`)
- **Server Separation**: Clearly separates `server` and `client` logic.
- **Protocol Models**: `a2a.types` contains all Pydantic models for the protocol (Tasks, Messages, Artifacts).
- **Event-Driven**: Uses a dedicated `events` module with `EventQueue` and `QueueManager`.
- **Execution Abstraction**: `server.agent_execution` defines the `AgentExecutor` base class.

### 1.2 ACP Python SDK (`acp-python-sdk`)
- **Transport Agnostic**: Separates the `Connection` logic from specific transports (though only stdio is shipped).
- **Contrib Patterns**: `contrib` directory contains high-value patterns like `SessionAccumulator` and `PermissionBroker`.
- **Task Management**: Dedicated `task` module for dispatching and supervising work.

### 1.3 Toad (`toad`)
- **UI Structure**: Uses a clear separation for TUI elements: `screens` (high-level containers) and `widgets` (reusable components).
- **Protocol Implementation**: Houses ACP-specific logic in `toad.acp`.
- **ANSI Parsing**: Dedicated `ansi` module for parsing raw terminal streams (critical for our Server-Side Replay).
- **Data-Driven Agents**: Agents defined via TOML in `data/agents`, making the system extensible without code changes.

### 1.4 A2A Samples
- **Orchestration Patterns**: Shows "Host Agent" patterns where one agent's tools are actually calls to other agents.
- **FastAPI Integration**: Demonstrates serving static JS UIs from a FastAPI backend.

---

## 2. Structural Requirements for Vaultspec-A2A

Based on the ADRs, the project needs:
1. **Process Supervision**: To manage subprocesses and Job Objects.
2. **Protocol Translation**: To bridge A2A, ACP (patterns), and MCP.
3. **Workspace Management**: To handle Worktrees and Git Mutexes.
4. **Event Aggregation**: To source events to SQLite and manage the ANSI ring buffer.
5. **UI Layer**: A SvelteKit frontend bundled into the package.

---

## 3. Persistent Knowledge Tokens (Vagueness Indicators)

- `{{TRANS_LAYER}}`: The logic that maps ACP updates to A2A events.
- `{{EXEC_CORE}}`: The engine that actually runs the agent reasoned loops.
- `{{UI_ADAPTER}}`: The bridge between Python events and Svelte components.
- `{{PORT_MANAGER}}`: The logic for race-condition-proof port allocation.
