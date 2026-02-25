# A2A Protocol Specification Reference

- **Source:** [https://github.com/a2aproject/A2A](https://github.com/a2aproject/A2A)
- **Relevance:** 10/10 - The definitive standard for A2A communication.

## Core Concepts

### Agent Card

A JSON document describing an agent's identity, version, skills, and
endpoints.

- `name`: Human-readable name.
- `skills`: List of capabilities (functions/tools) the agent provides.
- `endpoints`: URLs for the agent's API (e.g., `/tasks`).

### Task Lifecycle

1. **Creation:** Client POSTs to `/tasks` with task details and parameters.
2. **Acceptance:** Agent returns 202 Accepted with a task ID.
3. **Execution:** Agent processes the task and streams updates (events).
4. **Completion:** Agent marks the task as COMPLETED or FAILED.

### Communication

- **Request/Response:** Standard HTTP for task creation and status checks.
- **Streaming:** Server-Sent Events (SSE) for real-time task progress and
  intermediate results.
- **Authentication:** Supported via standard HTTP mechanisms (Bearer tokens,
  etc.).
