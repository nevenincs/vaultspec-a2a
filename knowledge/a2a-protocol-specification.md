---
title: A2A Protocol Specification (Release Candidate V1.0)
source: https://a2a-protocol.org/latest/specification/
relevance: 10
---

# A2A Protocol Specification Summary (V1.0 RC)

The Agent2Agent (A2A) Protocol is an open standard for interoperability between independent AI agent systems. It enables discovery, task management, and secure information exchange without requiring access to internal agent states.

## 1. Specification Structure

The protocol is organized into three layers:

**Layer 1: Canonical Data Model**
Defines core structures (Task, Message, AgentCard, Part, Artifact, Extension) using Protocol Buffers as the normative source (`spec/a2a.proto`).

**Layer 2: Abstract Operations**
Describes fundamental capabilities (Send Message, Stream Message, Get Task, List Tasks, Cancel Task, Get Agent Card) independent of transport.

**Layer 3: Protocol Bindings**
Concrete mappings to JSON-RPC, gRPC, and HTTP/REST.

### Visual Representation of Layers

- **L1 (Data Model):** [Task] -> [Message] -> [AgentCard] -> [Part] -> [Artifact] -> [Extension]
- **L2 (Operations):** [Send Message] -> [Stream Message] -> [Get Task] -> [List Tasks] -> [Cancel Task] -> [Get Agent Card]
- **L3 (Bindings):** [JSON-RPC Methods] | [gRPC RPCs] | [HTTP/REST Endpoints] | [Custom Bindings]
*Dependencies flow from L1 -> L2 -> L3.*

---

## 2. Core Operations (L2)

| Operation | Input | Output | Description |
| :--- | :--- | :--- | :--- |
| **Send Message** | `SendMessageRequest` | `Task` OR `Message` | Initiates interaction. Returns a Task for async work or a direct Message. |
| **Send Streaming Message** | `SendMessageRequest` | `StreamResponse` | Real-time updates. Returns Task/Message followed by status/artifact events. |
| **Get Task** | `id`, `historyLength` | `Task` | Retrieves current state, artifacts, and history of a task. |
| **List Tasks** | `contextId`, `status`, `pageSize`, `pageToken` | `ListTasksResponse` | Cursor-based paginated list of tasks, sorted by update time (DESC). |
| **Cancel Task** | `id` | `Task` | Attempts to move a task to `TASK_STATE_CANCELED`. |
| **Subscribe to Task** | `id` | `StreamResponse` | Establishes a stream for updates on an existing non-terminal task. |
| **Get Extended Agent Card** | `tenant` | `AgentCard` | Fetches detailed, authenticated metadata (requires `extendedAgentCard` capability). |

---

## 3. Protocol Data Model (L1)

### 3.1 Core Objects

- **Task:** The unit of work. Contains `id`, `contextId`, `status` (TaskStatus), `artifacts` (array), `history` (Message array), and `metadata`.
- **Message:** A communication turn. Contains `messageId`, `role` (USER/AGENT), `parts` (array), and `referenceTaskIds`.
- **Part:** Content container. **OneOf**: `text` (string), `raw` (bytes/base64), `url` (string), or `data` (JSON any). Includes `mediaType`.
- **Artifact:** Task output. Contains `artifactId`, `name`, `parts` (array), and `metadata`.
- **TaskStatus:** Contains `state` (TaskState) and an optional `message`.

### 3.2 Task States

- **Terminal:** `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`.
- **Interrupted:** `INPUT_REQUIRED`, `AUTH_REQUIRED`.
- **Active:** `SUBMITTED`, `WORKING`.

### 3.3 Agent Discovery (Agent Card)

A manifest describing:

- `supportedInterfaces`: List of `url`, `protocolBinding`, and `protocolVersion`.
- `capabilities`: `streaming` (bool), `pushNotifications` (bool), `extendedAgentCard` (bool).
- `skills`: Array of functional abilities with `inputModes`/`outputModes` (MIME types).
- `securitySchemes`: Map of auth methods (OAuth2, APIKey, OIDC, mTLS, HTTPAuth).

---

## 4. Operation Semantics

### 4.1 Update Delivery Mechanisms

1. **Polling:** Periodic `GetTask` calls.
2. **Streaming:** SSE or gRPC streams delivering `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`.
3. **Push Notifications (Webhooks):** Agent sends HTTP POST with `StreamResponse` payload to client-registered URLs. Requires `PushNotificationConfig`.

### 4.2 Multi-Turn Continuity

- **contextId:** Logically groups related tasks and messages into a session.
- **taskId:** References a specific stateful unit of work.
- Agents must infer `contextId` if only `taskId` is provided. Mismatched IDs must be rejected.

### 4.3 Error Handling

Standardized mapping across bindings. Key A2A errors:

- `TaskNotFoundError` (-32001 / 404)
- `TaskNotCancelableError` (-32002 / 409)
- `PushNotificationNotSupportedError` (-32003 / 400)
- `ContentTypeNotSupportedError` (-32005 / 415)
- `VersionNotSupportedError` (-32009 / 400)

---

## 5. Protocol Bindings (L3)

### 5.1 JSON Mapping Conventions

- **Field Naming:** `camelCase` (e.g., `protocolVersion`).
- **Enums:** `SCREAMING_SNAKE_CASE` strings (e.g., `"TASK_STATE_WORKING"`).
- **Timestamps:** ISO 8601 UTC strings (`YYYY-MM-DDTHH:mm:ss.sssZ`).

### 5.2 Service Parameters

Transmitted via transport headers (e.g., HTTP Headers, gRPC Metadata).

- `A2A-Version`: Required for version negotiation (e.g., `1.0`).
- `A2A-Extensions`: Comma-separated list of supported extension URIs.

---

## 6. Extensions

Agents declare extensions in the `AgentCard`. Clients opt-in via `A2A-Extensions` header.

- **Extension Points:** `Message.metadata`, `Artifact.metadata`, and `Task.metadata`.
- **Requirement:** If an extension is marked `required: true` in the Agent Card and the client doesn't support it, the agent must return `ExtensionSupportRequiredError`.
