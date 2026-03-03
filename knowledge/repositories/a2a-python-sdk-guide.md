---
name: 'A2A Python SDK Guide'
date: 2026-25-02
type: reference
summary: 'Detailed repository guide covering architecture, directory map, key data flows, extension points, and critical module identification.'
maturity: 65
---

# A2A Python SDK Repository Guide

This document serves as a navigational guide for the [A2A Python SDK](https://github.com/a2aproject/a2a-python) repository. It maps the project structure, explains key components, and describes the data flow for both server and client implementations.

## 1. High-Level Architecture

The SDK is divided into three primary logical blocks:

1.  **Shared Types (`src/a2a/types.py`)**: Pydantic models generated from the canonical JSON schema. These define the "language" of A2A.
2.  **Server (`src/a2a/server/`)**: Framework for building agents. It handles HTTP/JSON-RPC/gRPC transport, task persistence, and event orchestration, leaving only the "business logic" for the developer to implement in an `AgentExecutor`.
3.  **Client (`src/a2a/client/`)**: Tools for consuming A2A agents. Includes discovery (`CardResolver`), transport abstraction, and a high-level `Client` interface.

## 2. Directory Map

### Core Data Models

- **`src/a2a/types.py`**: **CRITICAL**. Contains all Protocol Buffer definitions converted to Pydantic models (e.g., `Task`, `Message`, `AgentCard`, `SendMessageRequest`).

### Server-Side (`src/a2a/server/`)

The server side is built around the `AgentExecutor` pattern.

- **`apps/`**: Entry points for the application.
  - `starlette_app.py`: The standard HTTP server implementation using Starlette.
  - `fastapi_app.py`: Integration with FastAPI.
- **`agent_execution/`**:
  - **`agent_executor.py`**: **CRITICAL**. Abstract base class for agent logic. Developers implement `execute()` and `cancel()`.
  - `context.py`: Defines `RequestContext` passed to executors.
- **`request_handlers/`**:
  - `default_request_handler.py`: The "Controller". Orchestrates `AgentExecutor`, `TaskStore`, and `QueueManager` to handle incoming RPCs.
- **`events/`**:
  - `event_queue.py`: Interface for publishing events (`TaskStatusUpdate`, `Message`) back to the client.
  - `in_memory_queue_manager.py`: Default ephemeral queue for streaming responses.
- **`tasks/`**:
  - `task_store.py`: Interface for persisting task state.
  - `inmemory_task_store.py`: Default RAM-based implementation.

### Client-Side (`src/a2a/client/`)

The client side abstracts transport details.

- **`client.py`**: **CRITICAL**. The main `Client` interface.
- **`card_resolver.py`**: Logic for fetching and validating `AgentCard`s from URLs.
- **`transports/`**:
  - `jsonrpc.py`: Implementation of A2A over HTTP/JSON-RPC (SSE for streaming).
  - `grpc.py`: Implementation of A2A over gRPC.
- **`client_factory.py`**: Creates the appropriate client transport based on the Agent Card's supported interfaces.

### Utilities (`src/a2a/utils/`)

Helper functions to reduce boilerplate.

- **`message.py`**: Helpers like `new_agent_text_message`.
- **`task.py`**: Helpers like `new_task`, `completed_task`.
- **`artifact.py`**: Helpers for creating artifacts.

## 3. Key Data Flows

### Server: Handling a Message

1.  **Entry**: `A2AStarletteApplication` receives a POST request.
2.  **Routing**: `DefaultRequestHandler` identifies the RPC method (e.g., `sendMessage`).
3.  **Task Creation**: A new `Task` is created in the `TaskStore` (status: `SUBMITTED`).
4.  **Execution**: `AgentExecutor.execute(context, event_queue)` is called.
5.  **Streaming**:
    - The `AgentExecutor` performs work.
    - It calls `event_queue.enqueue_event(...)` to send updates (`working`, `output`, `completed`).
6.  **Response**: The server streams these events back to the client via SSE.

### Client: Sending a Message

1.  **Resolution**: `A2ACardResolver` fetches the Agent Card from the target URL.
2.  **Factory**: `ClientFactory` picks the best transport (e.g., JSON-RPC).
3.  **Request**: `Client.send_message_streaming` constructs a `SendStreamingMessageRequest`.
4.  **Transport**: `JSONRPCTransport` sends the HTTP POST.
5.  **Consumption**: The client yields events (`TaskStatusUpdate`, `Message`) as they arrive from the SSE stream.

## 4. Extension Points

- **Custom Storage**: Implement `TaskStore` (in `src/a2a/server/tasks/`) to save tasks to Postgres/Redis/etc.
- **Custom Logic**: Subclass `AgentExecutor` (in `src/a2a/server/agent_execution/`) to implement your agent's reasoning.
- **Custom Auth**: Middleware in `src/a2a/server/apps` or `src/a2a/client/middleware.py`.
