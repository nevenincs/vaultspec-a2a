---
title: Toad ACP Implementation Deep Audit
source: https://github.com/batrachianai/toad
relevance: 10
---

# Toad ACP Implementation Deep Audit

This document details the precise technical implementation of the Agent Client Protocol (ACP) within the `toad` repository, focusing on agent management, installation, authentication, bidirectional message passing, tool usage, safety, and streaming.

## 1. Agent Management and Installation
Toad operates as a generic ACP host; it has zero hardcoded, python-level integrations for specific LLMs (like Gemini, Claude, or Codex). Instead, agents are entirely data-driven via TOML manifests.

### 1.1 TOML Manifests (`src/toad/data/agents/*.toml`)
Each agent has a manifest defining its metadata, runtime command, and installation procedure.
- **Loading:** `src/toad/agents.py:read_agents()` reads the manifests using `tomllib` and registers them in the application state.
- **Installation:** The manifests contain an `[actions."*".install]` table with a `command` string. Toad's UI (`src/toad/screens/action_modal.py`) allows users to execute this command to globally install the agent via external package managers (e.g., `npm`, `cargo`, `uv`).

### 1.2 Agent Subprocess Execution (How they are called)
The agent is launched as an asynchronous child process in `src/toad/acp/agent.py` (`Agent._run_agent`) using `asyncio.create_subprocess_shell`. The execution string comes from the manifest's `run_command` field.
- **Claude Code:** Invoked as `claude-code-acp` (uses an open-source Zed adapter).
- **Gemini CLI:** Invoked as `gemini --experimental-acp` (native ACP support).
- **Codex CLI:** Invoked as `npx @zed-industries/codex-acp`.

## 2. Authentication Management
The ACP specification defines an `authMethods` array (e.g., OAuth, API Key) returned during the `initialize` handshake.
- **Toad Implementation:** While `src/toad/acp/agent.py` intercepts `response.get("authMethods")` and assigns it to `self.auth_methods`, a deep audit reveals Toad **does not** implement an authentication UI flow.
- **Conclusion:** Authentication is managed out-of-band. Users must authenticate the agents directly via their respective CLIs in a separate terminal (e.g., `gemini login`, `claude login`) before Toad can successfully use them.

## 3. Bidirectionality and Message Passing
The ACP bridge provides full bidirectional communication using JSON-RPC 2.0 over standard I/O streams.

### 3.1 Custom JSON-RPC Framework (`src/toad/jsonrpc.py`)
Toad implements its own typed JSON-RPC framework. The host exposes methods via decorators (e.g., `@jsonrpc.expose("fs/read_text_file")` and `@API.method()`). It relies on `typeguard` to enforce strict type checking at runtime against schemas defined in `src/toad/acp/protocol.py`.

### 3.2 I/O Loop
- **Client -> Agent:** Toad writes JSON strings directly to the subprocess's standard input (`process.stdin.write(b"%s\n" % request.body_json)`).
- **Agent -> Client:** The `Agent._run_agent` loop constantly awaits `process.stdout.readline()`. It decodes the JSON and dispatches incoming RPC requests or notifications to the internal host server.

## 4. Streaming Mechanism
Toad's implementation of streaming is strictly **unidirectional (Agent -> Client)** for textual generation, but bidirectional for terminal execution.

### 4.1 Agent-to-Client Streaming (Generation)
Agents stream their responses or "thoughts" using the `session/update` JSON-RPC notification.
- Toad's `rpc_session_update` method listens for `sessionUpdate` payloads of type `agent_message_chunk` and `agent_thought_chunk`.
- As these chunks arrive, Toad fires `MessagePump` events to progressively update the textual UI.

### 4.2 Client-to-Agent "Streaming"
- **Prompts are NOT Streamed:** The client does not stream the prompt to the agent. `src/toad/acp/api.py:session_prompt` sends the user's input and all loaded file contexts as a single array of `ContentBlock`s.
- **Terminal Streaming IS Supported:** If an agent executes a shell command via `terminal/create`, Toad streams the terminal output buffer and exit status back to the agent dynamically upon request via the `terminal/output` JSON-RPC endpoint.

## 5. Tool Usage and Safety
The host exposes its capabilities to the agent via JSON-RPC, enabling complex local interactions.

### 5.1 Tool Exposer
Tools are exposed in `src/toad/acp/agent.py`:
- `fs/read_text_file` & `fs/write_text_file`: For direct file manipulation.
- `terminal/create`, `terminal/kill`, `terminal/wait_for_exit`: For background process execution.

### 5.2 Safety & Permissions (Human-in-the-Loop)
Safety is strictly enforced through the ACP `session/request_permission` method.
- When an agent attempts a sensitive operation (like executing a terminal command), it pauses and issues a `request_permission` RPC call containing a `ToolCallUpdatePermissionRequest` and multiple `PermissionOption` objects (e.g., `allow_once`, `reject_always`).
- Toad pauses the event loop, intercepts the request, presents an interactive modal to the user, and resumes the RPC call with the user's selected `OutcomeSelected` decision.
