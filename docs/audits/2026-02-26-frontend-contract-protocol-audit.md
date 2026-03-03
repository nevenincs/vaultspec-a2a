---
date: 2026-02-26
type: audit
feature: frontend-contract-protocol
description: 'Protocol audit comparing the frontend-backend wire contract in lib/api/schemas/ against A2A proto, A2A Python SDK, ACP schema, and Toad reference, confirming intentional divergence per ADR-006.'
related:
  - docs/adrs/2026-02-26-006-protocol-ecosystem-bridge-adr.md
  - docs/adrs/2026-02-26-011-frontend-backend-contract-adr.md
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
---

# Protocol Audit: Frontend-Backend Wire Contract vs A2A/ACP Source SDKs

**Date:** 2026-02-26
**Scope:** `lib/api/schemas/`(ADR-011 wire contract) audited against:

-`knowledge/repositories/A2A/specification/a2a.proto`(808 lines, canonical
protobuf) -`knowledge/repositories/a2a-python/src/a2a/types.py`(2041 lines, SDK
Pydantic models) -`knowledge/repositories/acp-python-sdk/src/acp/schema.py`(2841 lines, ACP
models) -`knowledge/repositories/toad/src/toad/acp/protocol.py`(ACP TypedDict
reference) -`knowledge/repositories/a2a-samples/samples/python/agents/langgraph/`(A2A +
LangGraph integration example) -`knowledge/a2a-protocol-definitions.md`, `a2a-protocol-key-concepts.md`,
`a2a-protocol-streaming-and-async.md`, `a2a-protocol-life-of-a-task.md`

- `knowledge/repositories/a2a-python-sdk-guide.md`(SDK architecture guide)

## 1. Architectural Context: Why Our Schemas Diverge from A2A

**ADR-006 explicitly rejects A2A and ACP as integration protocols.** The
project uses native LangGraph for all internal agent orchestration:

> "We completely abandon the A2A and ACP protocol integrations in favor of a
> native LangGraph architecture, with MCP serving strictly as the boundary
> protocol." — ADR-006 §2

This means:

- Our frontend wire contract is **NOT** an A2A protocol implementation.
- A2A`Task`, `Message`, `Part`, `Artifact`are NOT carried directly over our
  WebSocket.
- ACP concepts (tool calls, permissions, plans) are consumed internally by
  `AcpChatModel` and translated into LangChain objects, then further
  translated by the Event Aggregator into our custom frontend events.

**However**, the A2A and ACP protocols are authoritative references for:

1. The shapes and semantics of data that flows through the system
2. Naming conventions and field structures
3. Streaming patterns and state machine design
4. Content typing and artifact handling

The audit below identifies where our schemas should be strengthened based on
these references.

## 2. A2A Protocol: Core Concepts vs Our Models

### 2.1 TaskState (A2A) vs AgentLifecycleState (Ours)

**A2A SDK** (`types.py:989-1002`):

```python
class TaskState(str, Enum):
    submitted = 'submitted'
    working = 'working'
    input_required = 'input-required'  # NOTE: hyphenated
    completed = 'completed'
    canceled = 'canceled'              # NOTE: single 'l'
    failed = 'failed'
    rejected = 'rejected'
    auth_required = 'auth-required'    # NOTE: hyphenated
    unknown = 'unknown'
```

**Our schema** (`enums.py:AgentLifecycleState`):

```python
class AgentLifecycleState(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"  # underscore, not hyphen
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"            # double 'l'
```

### Gaps identified

| Issue                        | Severity | Detail                                                                                                                                                                                                                                                   |
| ---------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Missing `submitted`state     | HIGH     | A2A's initial state when a task is created/acknowledged. Our frontend has no way to show "task received but not yet processing." The aggregator emits`working`immediately, but the gap between user message submission and first agent activity is real. |
| Missing`auth_required`state  | MEDIUM   | A2A defines this for when an agent needs authentication credentials. Relevant when`AcpChatModel`reports auth failures from CLIs. Currently these would surface as generic`failed`states.                                                                 |
| Missing`rejected`state       | LOW      | A2A uses this when an agent declines a task. Less relevant in our LangGraph-native architecture where the supervisor controls routing.                                                                                                                   |
| `cancelled`spelling          | LOW      | A2A uses American`canceled`(single l). Our enum uses British`cancelled`(double l). Cosmetic but could cause interop friction if A2A bridge is ever added.                                                                                                |
| `input_required`value format | MEDIUM   | A2A uses hyphenated`input-required`. We use underscored `input_required`. Consistent within our own protocol, but diverges from A2A convention.                                                                                                          |

**Recommendation:** Add `SUBMITTED = "submitted"`and`AUTH_REQUIRED =
"auth_required"`to`AgentLifecycleState`.

### 2.2 Content Typing: A2A Parts vs Flat Strings

**A2A SDK** (`types.py:1005-1325`):

```python
class TextPart(A2ABaseModel):
    kind: Literal['text'] = 'text'
    text: str
    metadata: dict[str, Any] | None = None

class FilePart(A2ABaseModel):
    file: FileWithBytes | FileWithUri
    kind: Literal['file'] = 'file'
    metadata: dict[str, Any] | None = None

class DataPart(A2ABaseModel):
    data: dict[str, Any]
    kind: Literal['data'] = 'data'
    metadata: dict[str, Any] | None = None

class Part(RootModel[TextPart | FilePart | DataPart]):
    root: TextPart | FilePart | DataPart
```

### Our schema

- `MessageChunkEvent.content: str`— flat string -`ThoughtChunkEvent.content: str`— flat string -`ArtifactUpdateEvent.content: str`— flat string -`MessageSnapshot.content: str`— flat string

**Gap:** Every content field in our schemas is a flat`str`. This works for
streaming text tokens but cannot carry files, structured data, or metadata.
When `AcpChatModel`receives an`ImageContent`or`EmbeddedResourceContent`
from a CLI, it has no way to forward that through our event models.

**Recommendation:** This is acceptable for the initial streaming wire contract
because:

1. Streaming chunks are inherently text tokens (the LLM generates text).
2. File artifacts come through `ArtifactUpdateEvent`which has`filename`.
3. Rich content can be added later without breaking existing consumers
   (additive change per ADR-011 §5 Schema Evolution).

However, `MessageSnapshot` in the replay models should support typed parts for
full-fidelity replay. Flag for future iteration.

### 2.3 Artifact Model

**A2A SDK** (`types.py:1372-1400`):

```python
class Artifact(A2ABaseModel):
    artifact_id: str
    description: str | None = None
    extensions: list[str] | None = None
    metadata: dict[str, Any] | None = None
    name: str | None = None
    parts: list[Part]  # <-- typed content blocks
```

**A2A streaming** (`types.py:1603-1636`):

```python
class TaskArtifactUpdateEvent(A2ABaseModel):
    append: bool | None = None
    artifact: Artifact          # <-- full Artifact object
    context_id: str
    kind: Literal['artifact-update'] = 'artifact-update'
    last_chunk: bool | None = None
    metadata: dict[str, Any] | None = None
    task_id: str
```

### Our schema: (2)

```python
class ArtifactUpdateEvent(EventEnvelope):
    artifact_id: str
    filename: str               # <-- not in A2A
    content: str                # <-- flat string, not parts
    append: bool = False
    last_chunk: bool = False
```

### Gaps

| Issue                           | Severity | Detail                                                                                                 |
| ------------------------------- | -------- | ------------------------------------------------------------------------------------------------------ |
| `content: str`instead of`parts` | MEDIUM   | Cannot carry binary or structured artifacts. Acceptable for text-only MVP.                             |
| `filename`not in A2A artifact   | LOW      | A2A uses`FilePart.file.name`inside the parts list. Our flattened`filename`is simpler for the frontend. |
| Missing`description`field       | LOW      | A2A artifacts can carry descriptions for display.                                                      |
| Missing`metadata`field          | LOW      | Limits extensibility.                                                                                  |

### 2.4 Task and Message Models

**A2A SDK** —`Task` (`types.py:1855-1887`):

```python
class Task(A2ABaseModel):
    id: str
    context_id: str
    status: TaskStatus          # state + message + timestamp
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    kind: Literal['task'] = 'task'
    metadata: dict[str, Any] | None = None
```

**A2A SDK** — `Message` (`types.py:1436-1477`):

```python
class Message(A2ABaseModel):
    message_id: str
    role: Role                  # user | agent
    parts: list[Part]           # typed content
    context_id: str | None = None
    task_id: str | None = None
    kind: Literal['message'] = 'message'
    reference_task_ids: list[str] | None = None
    extensions: list[str] | None = None
    metadata: dict[str, Any] | None = None
```

**Our schema** — We have no `Task`or`Message`model. Our`thread_id`maps
to A2A's`context_id`. Our `ThreadStateSnapshot`partially covers`Task`.

**Assessment:** This is correct per ADR-006. A2A `Task`and`Message`are
A2A-protocol-specific types. Our frontend doesn't speak A2A — it speaks our
custom WebSocket protocol. The LangGraph`thread_id` + checkpointer state
replaces A2A's Task model.

### 2.5 Streaming Events

**A2A SDK** — Two event types (`types.py:1603-1689`):

```python
class TaskStatusUpdateEvent(A2ABaseModel):
    task_id: str
    context_id: str
    status: TaskStatus
    final: bool                 # <-- "is this the last event?"
    kind: Literal['status-update'] = 'status-update'
    metadata: dict[str, Any] | None = None

class TaskArtifactUpdateEvent(A2ABaseModel):
    task_id: str
    context_id: str
    artifact: Artifact
    append: bool | None = None
    last_chunk: bool | None = None
    kind: Literal['artifact-update'] = 'artifact-update'
    metadata: dict[str, Any] | None = None
```

**Our schema** — 12 granular event types covering agent status, message
chunks, thought chunks, tool calls, permissions, artifacts, plans, team
status, errors, connection, and heartbeat.

**Assessment:** A2A has 2 generic event types; we have 12 specialized ones.
This is by design — the A2A protocol is meant for opaque inter-agent
communication, while our frontend wire contract provides fine-grained UI
updates. The specialization is correct.

**Gap identified:** A2A's `final: bool`field on`TaskStatusUpdateEvent`is a
useful pattern we're missing. The frontend currently infers "stream complete"
from terminal`AgentLifecycleState`values. An explicit`final` flag would be
more reliable.

## 3. ACP Protocol: Tool Calls and Permissions

### 3.1 ToolCall Shapes

**ACP SDK** (`schema.py`—`ToolCall`, `ToolCallStart`, `ToolCallUpdate`):

The ACP SDK defines THREE distinct tool call models:

- `ToolCallStart`— initial tool invocation -`ToolCallProgress`— incremental updates (replaces content array) -`ToolCallUpdate` — partial updates merging into existing state

**Toad protocol** (`protocol.py:202-228`):

```python
class ToolCall(SchemaDict, total=False):
    toolCallId: Required[ToolCallId]
    title: Required[str]
    status: ToolCallStatus
    kind: ToolKind
    content: list[ToolCallContent]
    locations: list[ToolCallLocation]
    rawInput: dict
    rawOutput: dict
    sessionUpdate: Required[Literal["tool_call"]]
```

### Our schema: (3)

```python
class ToolCallStartEvent(EventEnvelope):
    tool_call_id: str
    title: str
    kind: ToolKind
    status: ToolCallStatus = ToolCallStatus.PENDING
    locations: list[ToolCallLocation]
    content: list[ToolCallContent]
```

**Alignment:** Good. Our `ToolCallStartEvent`and`ToolCallUpdateEvent`mirror
the Toad/ACP split correctly. Field names are snake_case (our convention) vs
camelCase (ACP convention), which is expected.

### Gaps: (2)

| Issue                           | Severity | Detail                                                                                                               |
| ------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------- |
| Missing`raw_input`/`raw_output` | LOW      | ACP carries the raw LLM tool call input/output. Useful for debugging but noisy for the frontend. Can be added later. |

### 3.2 ToolCallContent

**Toad protocol** (`protocol.py:154-175`):

```python
class ToolCallContentContent(SchemaDict, total=False):
    content: Required[ContentBlock]
    type: Required[Literal["content"]]

class ToolCallContentDiff(SchemaDict, total=False):
    newText: Required[str]
    oldText: str | None
    path: Required[str]
    type: Required[Literal["diff"]]

class ToolCallContentTerminal(SchemaDict, total=False):
    terminalId: Required[str]
    type: Required[Literal["terminal"]]
```

### Our schema: (4)

```python
class ToolCallContentText(BaseModel):
    content_type: Literal["text"] = "text"
    text: str

class ToolCallContentDiff(BaseModel):
    content_type: Literal["diff"] = "diff"
    path: str
    old_text: str | None = None
    new_text: str

class ToolCallContentTerminal(BaseModel):
    content_type: Literal["terminal"] = "terminal"
    terminal_id: str
```

### Gaps: (3)

| Issue                                           | Severity | Detail                                                                                                                                                                                                                                                                    |
| ----------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Discriminator name: `content_type`vs`type`      | LOW      | ACP uses`type`. We use `content_type`to avoid shadowing Python's`type`builtin. Reasonable divergence.                                                                                                                                                                     |
| `ToolCallContentContent`vs`ToolCallContentText` | MEDIUM   | ACP's first variant is`content`type carrying a full`ContentBlock`(which itself is a union of text/image/audio/embedded/resource-link). Our`ToolCallContentText`only carries a`text: str`. We lose the ability to carry images or embedded resources in tool call content. |

**Recommendation:** For MVP, `text` is sufficient since CLI tool outputs are
text. Document the gap for future iteration.

### 3.3 Permission Options

**ACP SDK** (`schema.py`/ Toad`protocol.py:328-338`):

```python
type PermissionOptionKind = Literal[
    "allow_once", "allow_always", "reject_once", "reject_always"
]
class PermissionOption(TypedDict, total=False):
    kind: Required[PermissionOptionKind]
    name: Required[str]
    optionId: Required[PermissionOptionId]
```

### Our schema: (5)

```python
class PermissionOptionKind(StrEnum):
    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    REJECT_ONCE = "reject_once"
    REJECT_ALWAYS = "reject_always"

class PermissionOption(BaseModel):
    option_id: str
    name: str
    kind: PermissionOptionKind
```

**Assessment:** Exact match. Field names differ only in case convention
(snake_case vs camelCase), which is our standard.

### 3.4 PlanEntry

**Toad protocol** (`protocol.py:244-248`):

```python
class PlanEntry(SchemaDict, total=False):
    content: Required[str]
    priority: Literal["high", "medium", "low"]
    status: Literal["pending", "in_progress", "completed"]
```

### Our schema: (6)

```python
class PlanEntry(BaseModel):
    content: str
    status: PlanEntryStatus = PlanEntryStatus.PENDING
    priority: PlanEntryPriority = PlanEntryPriority.MEDIUM
```

**Assessment:** Exact match with proper defaults.

## 4. A2A LangGraph Sample: Integration Patterns

The A2A samples repository at `a2a-samples/samples/python/agents/langgraph/`
shows the canonical pattern for A2A + LangGraph integration:

1. **`agent.py`** — Creates a `create_react_agent()`with`MemorySaver` for
   checkpointing. Streams output and maps LangGraph message types to A2A
   response format.

1. **`agent_executor.py`** — Implements A2A's `AgentExecutor`interface:
   - Iterates LangGraph`stream()`output
   - Maps`AIMessage`with`tool_calls`→`TaskState.working`
   - Maps final response → `TaskState.completed`with`TextPart`artifact
   - Maps`input_required`→`TaskState.input_required`

1. **State mapping pattern:**

```text
LangGraph thread_id  ←→  A2A context_id
LangGraph stream items  ←→  A2A streaming events
LangGraph AIMessage  ←→  A2A Message (role=agent)
Pydantic ResponseFormat  ←→  A2A Artifact
```

**Relevance to our schemas:** This pattern confirms that our event
aggregator should:

- Map LangGraph `astream_events`→ our 12 event types
- Use`thread_id`as the equivalent of A2A`context_id`
- Use `sequence`counters for ordering (A2A has no equivalent — it uses
  `final: bool`instead)

## 5. Summary of Findings

### What We Got Right

1. **ToolKind, ToolCallStatus, PermissionOptionKind, PlanEntry** — exact
   match with ACP/Toad protocol definitions.
2. **ToolCallStart/ToolCallUpdate split** — correctly mirrors ACP's
   tool_call / tool_call_update pattern.
3. **Discriminated unions with`type` field** — correct approach for O(1)
   dispatch.
4. **Connection-scoped vs thread-scoped event separation** — no A2A
   equivalent, but architecturally sound.
5. **`sequence`counter for gap detection** — superior to A2A's`final: bool`
   approach for reconnection.
6. **REST fallback for permissions** — addresses a real reliability gap that
   A2A's SSE-only approach doesn't solve.

### Gaps to Address

| #   | Gap                                                             | Source                     | Severity  | Action                                                                                      |
| --- | --------------------------------------------------------------- | -------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| 1   | Missing `submitted`and`auth_required`lifecycle states           | A2A TaskState              | HIGH      | Add to`AgentLifecycleState`                                                                 |
| 2   | No`metadata: dict[str, Any]`extensibility on events             | A2A pattern                | MEDIUM    | Add optional`metadata`to`EventEnvelope`and connection events                                |
| 3   | No`context_id`field on events/commands                          | A2A Task/Message           | MEDIUM    | Our`thread_id`serves this role. Add`context_id`as alias or document the mapping explicitly. |
| 4   | `content: str`cannot carry non-text data                        | A2A Part union             | LOW (MVP) | Acceptable for streaming tokens. Flag for future`Part`-based content.                       |
| 5   | Missing `final`flag on terminal events                          | A2A TaskStatusUpdateEvent  | LOW       | Can be inferred from terminal states, but explicit flag is cleaner.                         |
| 6   | `ToolCallContentText`only carries`str`, not full `ContentBlock` | ACP ToolCallContentContent | LOW (MVP) | Sufficient for text tool outputs.                                                           |
| 7   | `ArtifactUpdateEvent`uses flat`content: str`, not `parts`       | A2A Artifact               | LOW (MVP) | Acceptable for text artifacts.                                                              |

### What Does NOT Need to Change

- **No A2A`Task`or`Message`model needed** — ADR-006 explicitly replaces
  these with LangGraph's native state management.
- **No JSON-RPC 2.0 envelope needed** — our WebSocket protocol uses its own
  envelope. JSON-RPC is an A2A transport detail.
- **No`AgentCard`model needed in frontend schemas** — agent discovery is
  internal to the LangGraph graph. The frontend sees agents via
  `AgentSummary`in`TeamStatusEvent`.
- **`kind`vs`type`discriminator naming** — A2A uses`kind`, we use
  `type`. Both are valid. Ours is more conventional for WebSocket protocols.

## 6. Recommended Changes

### Immediate (before next iteration)

1. Add `SUBMITTED = "submitted"`and`AUTH_REQUIRED = "auth_required"`to
   `AgentLifecycleState`enum.
   | 2. Add`metadata: dict[str, Any] | None = None`to`EventEnvelope`base |
   model.
   | 3. Add`metadata: dict[str, Any] | None = None`to`ConnectedEvent`and |
   `HeartbeatEvent`.

### Deferred (future iteration, additive)

1. Typed `Part`union for`MessageSnapshot.content`(text/file/data). 2.`final: bool`field on terminal server events. 3.`raw_input`/`raw_output`on tool call events for debugging. 4.`description`field on`ArtifactUpdateEvent`.
