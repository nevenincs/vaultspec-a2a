---
title: ACP Tool Content Preservation — Fix Design
date: 2026-03-06
type: research
related:
  - docs/research/2026-03-06-derisking-coding-challenges-research.md
  - docs/adrs/011-frontend-backend-contract.md
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
---

## ACP Tool Content Preservation: Fix Design

## Problem Statement

`AcpChatModel._on_tool_call` receives the full ACP `ToolCall` payload from the
subprocess but strips all rich fields (`kind`, `content`, `locations`, `status`)
when converting to LangChain's `ToolCallChunk`. The aggregator's `on_tool_start`
and `on_tool_end` handlers therefore cannot emit accurate `ToolCallStartEvent`,
`ToolCallUpdateEvent`, or `ArtifactUpdateEvent` wire events.

## 1. Available ACP Fields in Raw Events

### 1.1 `tool_call` (sessionUpdate)

From `knowledge/repositories/toad/src/toad/acp/protocol.py` lines 202-213:

| Field | Type | Description |
|-------|------|-------------|
| `toolCallId` | `str` (required) | Unique tool call identifier |
| `title` | `str` (required) | Human-readable tool name (e.g. "Edit", "Read") |
| `kind` | `ToolKind` | `"read"` \| `"edit"` \| `"delete"` \| `"move"` \| `"search"` \| `"execute"` \| `"think"` \| `"fetch"` \| `"switch_mode"` \| `"other"` |
| `status` | `ToolCallStatus` | `"pending"` \| `"in_progress"` \| `"completed"` \| `"failed"` |
| `content` | `list[ToolCallContent]` | Rich content blocks — see 1.3 |
| `locations` | `list[ToolCallLocation]` | File path + optional line number |
| `rawInput` | `dict` | Raw tool arguments |
| `rawOutput` | `dict` | Raw tool result |

### 1.2 `tool_call_update` (sessionUpdate)

From protocol.py lines 217-228. Same fields as `tool_call` but all optional
except `toolCallId`. Updates are incremental — only changed fields are present.

### 1.3 ToolCallContent Types

Three content block variants (protocol.py lines 154-175):

| Type | Fields | Use Case |
|------|--------|----------|
| `content` | `{type: "content", content: {type: "text", text: "..."}}` | Text output (command results, explanations) |
| `diff` | `{type: "diff", path: "...", oldText: "...", newText: "..."}` | File edits with unified diff |
| `terminal` | `{type: "terminal", terminalId: "..."}` | Terminal session reference |

### 1.4 ToolCallLocation

```python
class ToolCallLocation(SchemaDict, total=False):
    line: int | None
    path: Required[str]  # File path affected by the tool
```text

## 2. Where Data Is Stripped

### 2.1 `_on_tool_call` (line 1010)

```python
async def _on_tool_call(self, update: dict, ctx: _AcpSessionContext) -> None:
    tid = update.get("toolCallId", "")
    self._tool_calls[tid] = dict(update)      # <-- Full data stored internally
    chunk = ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            tool_call_chunks=[{                 # <-- Only 4 fields forwarded
                "id": tid,
                "name": update.get("title", ""),
                "args": json.dumps(update.get("input")),
                "index": 0,
            }],
        )
    )
    ctx.chunk_queue.put_nowait(chunk)
```yaml

**Stripped fields**: `kind`, `status`, `content`, `locations`, `rawInput`,
`rawOutput`. Note that `update.get("input")` is used (does not exist in ACP
schema — should be `rawInput`), so `args` is likely always `"null"`.

### 2.2 `_on_tool_call_update` (line 1033)

Same pattern. The internal `self._tool_calls[tid]` dict is updated with all
fields, but no chunk is emitted for updates (only for synthesized late arrivals).
The `status` field is logged but not forwarded.

### 2.3 `plan` session update (line 1004)

```python
elif u_type == "plan":
    plan_steps = update.get("plan", {}).get("steps", [])
    logger.debug("ACP plan update: %d steps received", len(plan_steps))
```text

Plan data from ACP is logged and discarded. The actual ACP schema uses
`update.get("entries")` (not `update.get("plan", {}).get("steps", [])`), so
this code reads nothing even if plans are present.

## 3. Recommended Fix: Stash in `additional_kwargs` (Option B)

### 3.1 Approach

Stash the full ACP tool call/update payload in `AIMessageChunk.additional_kwargs`
so it survives through LangGraph's event pipeline and is accessible to the
aggregator's `on_tool_start`/`on_tool_end` handlers.

### 3.2 Concrete Change in `_on_tool_call`

```python
async def _on_tool_call(self, update: dict, ctx: _AcpSessionContext) -> None:
    tid = update.get("toolCallId", "")
    self._tool_calls[tid] = dict(update)

    # Preserve rich ACP data for downstream aggregator consumption.
    # Keyed as a list to survive merge_dicts accumulation safely.
    acp_payload = {
        "toolCallId": tid,
        "kind": update.get("kind", "other"),
        "status": update.get("status"),
        "locations": update.get("locations"),
        "content": update.get("content"),
    }

    chunk = ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            tool_call_chunks=[{
                "id": tid,
                "name": update.get("title", ""),
                "args": json.dumps(update.get("rawInput")),  # Fix: rawInput not input
                "index": 0,
            }],
            additional_kwargs={"acp_tool_calls": [acp_payload]},
        )
    )
    ctx.chunk_queue.put_nowait(chunk)
```text

### 3.3 Concrete Change in `_on_tool_call_update`

Emit a chunk for every status-bearing update (not just synthesized late arrivals):

```python
async def _on_tool_call_update(self, update: dict, ctx: _AcpSessionContext) -> None:
    tid = update.get("toolCallId", "")
    if tid not in self._tool_calls:
        self._tool_calls[tid] = {"toolCallId": tid, "title": update.get("title", tid)}
        # Synthesize initial tool_call_chunk (existing behavior)
        ...

    for k, v in update.items():
        if v is not None:
            self._tool_calls[tid][k] = v

    # Forward status + content updates as additional_kwargs
    if update.get("status") or update.get("content"):
        acp_payload = {
            "toolCallId": tid,
            "kind": update.get("kind") or self._tool_calls[tid].get("kind", "other"),
            "status": update.get("status"),
            "locations": update.get("locations") or self._tool_calls[tid].get("locations"),
            "content": update.get("content"),
        }
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                additional_kwargs={"acp_tool_calls": [acp_payload]},
            )
        )
        try:
            ctx.chunk_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            logger.warning("Chunk queue full — dropping tool_call_update enrichment")
```text

## 4. LangChain Chunk Accumulation: Will `additional_kwargs` Survive?

### 4.1 Merge Mechanics (Verified Against Source)

`AIMessageChunk.__add__` calls `add_ai_message_chunks()` (langchain-core
`messages/ai.py`), which calls:

```python
additional_kwargs = merge_dicts(
    left.additional_kwargs, *(o.additional_kwargs for o in others)
)
```text

`merge_dicts` (langchain-core `utils/_merge.py`) handles these type-specific
merge strategies:

| Value Type | Strategy |
|-----------|----------|
| `dict` | Recursive `merge_dicts` (deep merge) |
| `list` | `merge_lists` (append/index-merge) |
| `str` | Concatenation |
| `int` | Sum (except `index`/`created`/`timestamp` which use last-wins) |
| `None` in left | Right value wins |

### 4.2 Empirical Verification

Tested with the installed langchain-core version:

```python
chunk_a = AIMessageChunk(content='', additional_kwargs={
    'acp_tool_calls': [{'toolCallId': 'tc1', 'kind': 'edit'}]
})
chunk_b = AIMessageChunk(content='', additional_kwargs={
    'acp_tool_calls': [{'toolCallId': 'tc2', 'kind': 'read'}]
})
merged = chunk_a + chunk_b
# Result: {'acp_tool_calls': [{'toolCallId': 'tc1', ...}, {'toolCallId': 'tc2', ...}]}
```text

**Lists are safely appended.** Each tool call payload is preserved as a distinct
list element.

### 4.3 CRITICAL: Do NOT Use a Dict Key

Using a plain dict (`acp_tool_call: {...}`) causes `merge_dicts` to deep-merge
the inner dicts, which **concatenates strings**:

```python
# BAD: merge_dicts concatenates string values
{'acp_tool_call': {'toolCallId': 'tc1', 'kind': 'edit'}}
+ {'acp_tool_call': {'toolCallId': 'tc2', 'kind': 'read'}}
= {'acp_tool_call': {'toolCallId': 'tc1tc2', 'kind': 'editread'}}  # CORRUPTED
```text

The key **must** be `acp_tool_calls` (list-valued) to avoid corruption during
chunk accumulation.

### 4.4 Survival Through LangGraph

LangGraph's `astream_events(version="v2")` / `astream(stream_mode="messages")`
yields individual `AIMessageChunk` objects without accumulating them — each chunk
passes through with its `additional_kwargs` intact. The aggregator receives
per-chunk events and can inspect `additional_kwargs["acp_tool_calls"]` on each.

For `stream_mode="updates"` (node-level state diffs), the accumulated message
is stored in state. The list-valued `acp_tool_calls` accumulates all tool call
payloads for the entire turn — the aggregator would need to track which ones it
has already processed.

**Recommendation**: Read `acp_tool_calls` from individual stream chunks (via
`on_chat_model_stream` events), not from accumulated state.

## 5. Aggregator Integration

### 5.1 Reading ACP Data in `process_langgraph_event`

The aggregator's `on_chat_model_stream` handler already receives
`AIMessageChunk` objects. Add inspection:

```python
if event_kind == "on_chat_model_stream":
    chunk = event_data.get("data", {}).get("chunk")
    if isinstance(chunk, AIMessageChunk):
        acp_tools = chunk.additional_kwargs.get("acp_tool_calls", [])
        for tool_data in acp_tools:
            kind = tool_data.get("kind", "other")
            status = tool_data.get("status")
            locations = tool_data.get("locations", [])
            content = tool_data.get("content", [])

            # Emit ToolCallStartEvent / ToolCallUpdateEvent with rich data
            # Emit ArtifactUpdateEvent for completed edit/delete/move with diff content
```text

### 5.2 ArtifactUpdateEvent Detection

When `status == "completed"` and `kind in ("edit", "delete", "move")`:

1. Extract filename from `locations[0]["path"]`
2. Extract diff content from `content` blocks with `type == "diff"`
3. Emit `ArtifactUpdateEvent(filename=..., content=...)`

## 6. Plan Update Forwarding (Bonus Fix)

The `plan` session update handler (line 1004) has a schema mismatch. ACP sends:

```python
{"sessionUpdate": "plan", "entries": [{"content": "...", "status": "pending"}]}
```text

Current code reads `update.get("plan", {}).get("steps", [])` — always empty.

Fix: Forward plan entries via `additional_kwargs` using the same list pattern:

```python
elif u_type == "plan":
    entries = update.get("entries", [])
    if entries:
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                additional_kwargs={"acp_plan_entries": entries},
            )
        )
        ctx.chunk_queue.put_nowait(chunk)
```text

## 7. Summary

| Question | Answer |
|----------|--------|
| What ACP fields are available? | `kind`, `status`, `content` (3 types), `locations`, `rawInput`, `rawOutput` |
| Where is data stripped? | `_on_tool_call` line 1013-1024 — only `id`, `name`, `args`, `index` forwarded |
| Minimal preservation fix? | Stash in `additional_kwargs={"acp_tool_calls": [payload]}` (list-valued) |
| Does chunk accumulation preserve it? | YES — `merge_dicts` appends lists safely. Dict keys would corrupt via string concatenation. |
| Additional bug found? | `update.get("input")` should be `update.get("rawInput")` (ACP schema) |
| Additional bug found? | `plan` handler reads wrong path (`plan.steps` vs `entries`) |
