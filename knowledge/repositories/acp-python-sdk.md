# Agent Client Protocol (ACP) Python SDK Reference

- **Source:** [https://github.com/agentclientprotocol/python-sdk](https://github.com/agentclientprotocol/python-sdk)
- **Relevance:** 9/10 - Essential for IDE integration.

## Overview

ACP is designed for local and remote communication between coding agents and editors. It uses JSON-RPC as the primary transport.

## Key Features

- **Pydantic Models:** Strictly typed models for all ACP messages and schema objects.
- **Transports:**
  - `StdioTransport`: For local agents running as subprocesses.
  - `HttpTransport`: For remote agents communicating via JSON-RPC over HTTP.
- **Agent Base Class:** Simplifies the creation of ACP-compliant agents.

## Protocol Highlights

- **Initialization:** Handshake process to negotiate capabilities.
- **Task Delegation:** IDEs delegate coding tasks to agents.
- **Tool Use:** Agents can call tools provided by the IDE (e.g., `read_file`, `edit_file`).
