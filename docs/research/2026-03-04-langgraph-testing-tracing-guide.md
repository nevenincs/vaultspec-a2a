# LangGraph Testing & Tracing Guide

**Date**: 2026-03-04
**Author**: docs-researcher agent
**Status**: Final
**Related ADRs**: ADR-027 (Agentic Evaluation Architecture)

---

## Overview

This document grounds the team in official LangGraph testing and LangSmith tracing
documentation. All claims are sourced from context7 MCP queries against
`/websites/langchain_oss_python_langgraph` (900 snippets, benchmark 86.9) and the
`docs-langchain` MCP server.

---

## 1. Official LangGraph Testing Patterns

Source: https://langchain-ai.github.io/langgraph/concepts/testing/

### 1.1 Unit Testing Individual Nodes

Test node logic in isolation by invoking `compiled_graph.nodes["node_name"]` directly.
This bypasses the graph routing and lets you assert on pure node input→output.

```python
# Compile the graph
compiled = graph.compile()

# Invoke a single node directly
result = compiled.nodes["my_node"].invoke({"my_key": "initial_value"})
assert result["my_key"] == "expected_value"
```

This is the correct Layer 1 approach: deterministic, no LLM routing involved.

### 1.2 Unit Testing the Full Graph with MemorySaver

For testing complete graph execution with controlled state:

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
compiled = graph.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "test-thread-1"}}
result = compiled.invoke({"input": "test input"}, config)
assert result["output"] == "expected output"
```

`MemorySaver` is the canonical in-process, in-memory checkpointer for tests.
Do NOT use `AsyncSqliteSaver` in Layer 1 tests — it requires file I/O and
introduces flakiness. The `MemorySaver` is imported from `langgraph.checkpoint.memory`.

### 1.3 Partial Execution with `interrupt_after`

To test graph state at an intermediate node before continuing:

```python
# Run graph and stop after "node_a"
config = {"configurable": {"thread_id": "test-partial"}}
result = compiled.invoke(
    {"input": "value"},
    config,
    interrupt_after=["node_a"],
)

# Inspect state at this checkpoint
snapshot = compiled.get_state(config)
assert snapshot.values["intermediate_key"] == "expected"

# Inject modified state and resume
compiled.update_state(config, {"intermediate_key": "overridden"}, as_node="node_a")
final = compiled.invoke(None, config)
```

Note: `interrupt_after` is a compile-time or invoke-time option, not a node
configuration. This differs from `interrupt()` (runtime suspension for human-in-the-loop).

### 1.4 Interrupt / Resume Testing

For testing `interrupt()` suspension and `Command(resume=...)` resume:

```python
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

compiled = graph.compile(checkpointer=MemorySaver())
config = {"configurable": {"thread_id": "interrupt-test"}}

# First invocation — graph suspends at interrupt()
result = compiled.invoke({"input": "test"}, config)
assert "__interrupt__" in result

interrupt_value = result["__interrupt__"][0].value
# Inspect the interrupt payload
assert interrupt_value["type"] == "permission_request"

# Resume with a response
final = compiled.invoke(Command(resume="approved_option_id"), config)
assert final["status"] == "completed"
```

This is the pattern established in `src/vaultspec_a2a/core/tests/test_supervisor.py` lines 663-688.
The `Command` type is imported from `langgraph.types`.

### 1.5 What NOT to Test in Layer 1

Per ADR-027 and official LangGraph documentation, these are forbidden in pytest:

- Asserting routing decisions made by a real LLM (`assert result["next"] == "planner"`)
- Asserting content of LLM-generated text (`assert "def " in generated_code`)
- Asserting plan quality or reviewer completeness
- Any `@pytest.mark.live` test for agent behaviour

The LangGraph documentation explicitly recommends `FakeListChatModel` (from
`langchain_core.language_models.fake`) as the correct stub for deterministic node
testing. This model returns pre-configured responses and never calls a real LLM.

---

## 2. LangSmith Tracing Integration

Source: https://langchain-ai.github.io/langgraph/concepts/observability/

### 2.1 Enabling Traces

Set these environment variables before running any graph:

```bash
# Current canonical name (as of LangSmith 0.2+)
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-key>

# Legacy aliases — also accepted by LangGraph runtime (backward-compatible)
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=<your-key>
```

The project `.env` uses `LANGSMITH_TRACING` and `LANGSMITH_API_KEY` — the canonical
current names per the LangSmith SDK. No code changes are required to enable tracing.

### 2.2 What Is Auto-Captured

LangGraph automatically captures the following in every trace without any code changes:

| Signal | What is captured |
|--------|-----------------|
| Node execution | Node name, input state, output state delta, latency |
| LLM calls | Model name, prompt, completion, token counts, latency |
| Tool calls | Tool name, arguments, result |
| State transitions | Full state snapshot at each checkpoint |
| Errors | Exception type, message, traceback, node where it occurred |
| Graph structure | Node graph topology (visualized in LangSmith UI) |

### 2.3 Custom Metadata and Tags

Pass metadata and tags via the `config` dict to group and filter traces:

```python
config = {
    "configurable": {"thread_id": "my-thread"},
    "tags": ["smoke-test", "gemini", "structured-coder"],
    "metadata": {
        "environment": "development",
        "team_preset": "vaultspec-structured-coder",
        "user_id": "test-user",
    },
}
result = await graph.ainvoke(input_state, config)
```

For programmatic trace grouping without modifying call sites, use the context manager:

```python
import langsmith as ls

with ls.tracing_context(
    project_name="vaultspec-smoke-tests",
    tags=["supervisor-routing"],
    metadata={"test_case": "structured-coder-plan-phase"},
):
    result = await graph.ainvoke(input_state, config)
```

### 2.4 Trace Structure in the LangSmith UI

Each `ainvoke` / `astream` call produces one **root run**. Within it:

```
Root Run (graph invocation)
├── Node Run: supervisor
│   └── LLM Run: ChatAnthropic
│       ├── Input: [SystemMessage, HumanMessage, ...]
│       └── Output: AIMessage (with tool_calls if routing)
├── Node Run: planner
│   └── LLM Run: ChatAnthropic
│       └── ...
├── Node Run: vaultspec-coder_tools   ← ToolNode
│   └── Tool Run: queue_task
│       └── Input/Output: Command(update={...})
└── Node Run: reviewer
    └── LLM Run: ChatAnthropic
        └── ...
```

Each node run shows: name, input state dict, output state delta, wall-clock latency.
Checkpoint state is captured at every node boundary (when using a checkpointer).

### 2.5 Project Grouping

Traces are grouped by project. The project is set via:

```bash
LANGSMITH_PROJECT=vaultspec-dev   # set in .env (legacy alias: LANGCHAIN_PROJECT)
```

Or per-run via config `metadata["ls_project"]` or `ls.tracing_context(project_name=...)`.

For the Layer 2 direct scripts, use a distinct project name per run type
(e.g., `vaultspec-smoke`, `vaultspec-integration`) to avoid polluting the dev trace stream.

---

## 3. `astream(stream_mode=...)` Modes

Source: https://langchain-ai.github.io/langgraph/concepts/streaming/

LangGraph's `astream()` supports four stream modes. They can be combined by passing
a list. This is the API used in `src/vaultspec_a2a/core/aggregator.py` (post-LG-018 fix).

### 3.1 `"updates"` — State Delta Per Node (Recommended)

```python
async for chunk in graph.astream(input, config, stream_mode="updates"):
    # chunk = {node_name: state_delta_dict}
    node_name, delta = next(iter(chunk.items()))
    print(f"Node {node_name!r} produced: {delta}")
```

- Yields once per node completion
- Contains only the keys that the node wrote (not the full state)
- Most efficient for streaming progress indicators
- This is what `aggregator.py` uses as its primary mode

### 3.2 `"values"` — Full State Per Step

```python
async for state in graph.astream(input, config, stream_mode="values"):
    # state = full TeamState dict after each node
    print(f"Current phase: {state.get('pipeline_phase')}")
```

- Yields the complete state snapshot after every node
- Higher bandwidth than `"updates"` — use when you need the full picture
- Useful for checkpointing and debugging

### 3.3 `"messages"` — LLM Token Chunks

```python
async for msg, metadata in graph.astream(input, config, stream_mode="messages"):
    # msg = AIMessageChunk with partial content
    # metadata = {"langgraph_node": "planner", "ls_model_name": "claude-sonnet-4-6", ...}
    if hasattr(msg, "content") and msg.content:
        print(msg.content, end="", flush=True)
```

- Yields `(AIMessageChunk, metadata)` tuples as tokens stream from the LLM
- `metadata["langgraph_node"]` identifies which node is generating the chunk
- This is the mode used by the frontend for streaming text rendering
- NOT produced for tool calls (only LLM text generation)

### 3.4 `"debug"` — Verbose Node + State Log

```python
async for event in graph.astream(input, config, stream_mode="debug"):
    # event = {"type": "task"|"task_result"|"checkpoint", "payload": {...}}
    print(event)
```

- Yields structured debug events: node start, node result, checkpoint written
- Highest verbosity — use only for deep debugging
- Not used in production aggregator

### 3.5 Combining Modes

```python
async for chunk in graph.astream(
    input, config, stream_mode=["messages", "updates"]
):
    # chunk = (stream_mode_str, data)
    mode, data = chunk
    if mode == "messages":
        msg, metadata = data
    elif mode == "updates":
        node_name, delta = next(iter(data.items()))
```

When multiple modes are combined, each chunk is a `(mode_name, payload)` tuple.
This is the pattern used in `src/vaultspec_a2a/core/aggregator.py` post-LG-018.

### 3.6 LangSmith Trace Relationship

All `astream` modes produce identical LangSmith traces — the stream mode only
affects what the Python caller receives, not what is sent to LangSmith.
LangSmith always captures the full execution regardless of stream mode.

---

## 4. Integration Testing Patterns for Supervisor, Multi-Agent, and Checkpoint/Resume

Source: https://langchain-ai.github.io/langgraph/concepts/multi_agent/ and testing docs

### 4.1 Supervisor Routing — Layer 1 Pattern

Use `FakeListChatModel` to deterministically control routing decisions:

```python
from langchain_core.language_models.fake import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver

# Pre-configure the LLM to return a specific routing decision
fake_llm = FakeListChatModel(responses=[
    '{"next": "planner"}'   # JSON tool call or structured output
])

# Build graph with fake LLM injected
graph = compile_team_graph(config, llm=fake_llm)
compiled = graph.compile(checkpointer=MemorySaver())

config = {"configurable": {"thread_id": "routing-test-1"}}
result = await compiled.ainvoke(input_state, config)

# Assert routing was applied — this is a code-correctness assertion (ALLOWED)
assert result["pipeline_phase"] == "plan"
```

### 4.2 Multi-Agent Collaboration — Layer 2 Pattern

Multi-agent collaboration (supervisor routing to workers, workers producing artifacts)
involves real LLM routing and is therefore in Layer 2 (LangSmith tracing), not Layer 1.

Direct script approach:

```python
# scripts/smoke_structured_coder.py
import asyncio, os
from dotenv import load_dotenv
load_dotenv()  # sources LANGSMITH_TRACING, LANGSMITH_API_KEY

from lib.core import compile_team_graph
from lib.core.team_config import load_team_config

async def main():
    config = load_team_config("vaultspec-structured-coder")
    graph = compile_team_graph(config)
    result = await graph.ainvoke({
        "messages": [HumanMessage(content="Implement a binary search function in Python")],
        "thread_id": "smoke-structured-coder-001",
    }, {"configurable": {"thread_id": "smoke-structured-coder-001"}})
    print("Run complete — inspect trace in LangSmith")

asyncio.run(main())
```

### 4.3 Checkpoint / Resume — Layer 1 Pattern

Test the suspend→resume lifecycle with MemorySaver:

```python
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

# Build minimal graph that uses interrupt()
checkpointer = MemorySaver()
compiled = graph.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "resume-test-1"}}

# Step 1: invoke until interrupt
result1 = await compiled.ainvoke(initial_state, config)
assert "__interrupt__" in result1
interrupt_payload = result1["__interrupt__"][0].value

# Verify interrupt payload shape (code-correctness assertion — ALLOWED)
assert interrupt_payload["type"] == "permission_request"
assert "options" in interrupt_payload

# Step 2: resume with an option
option_id = interrupt_payload["options"][0]["id"]
result2 = await compiled.ainvoke(Command(resume=option_id), config)

# Verify post-resume state (code-correctness assertion — ALLOWED)
assert result2.get("routing_error") is None
```

### 4.4 State Injection via `update_state`

For testing graph branches without re-running prior nodes:

```python
# Set up a specific state at a checkpoint
compiled.update_state(
    config,
    {"pipeline_phase": "exec", "current_plan": [...]},
    as_node="supervisor",
)

# Resume from that injected state
result = await compiled.ainvoke(None, config)
assert result["pipeline_phase"] == "review"
```

`as_node` tells LangGraph to treat this as if the named node produced this state,
so the conditional edges from that node are re-evaluated.

### 4.5 The MemorySaver Thread Isolation Requirement

Each test MUST use a unique `thread_id` to avoid state leakage between tests:

```python
import uuid

config = {"configurable": {"thread_id": str(uuid.uuid4())}}
```

Alternatively, create a fresh `MemorySaver()` per test (via pytest fixture):

```python
@pytest.fixture
def checkpointer():
    return MemorySaver()

@pytest.fixture
def compiled_graph(checkpointer):
    return graph.compile(checkpointer=checkpointer)
```

A new `MemorySaver()` instance is always empty — no cross-test contamination.

---

## 5. Summary: Which Pattern for Which Scenario

| Scenario | Layer | Mechanism | Assertion Style |
|----------|-------|-----------|----------------|
| Reducer logic (`_append_artifacts`) | 1 | Direct function call | Pure Python assertEqual |
| Node logic (FakeListChatModel) | 1 | `compiled.nodes["n"].invoke()` | State key assertions |
| Supervisor routing (fake LLM) | 1 | `compiled.ainvoke()` + MemorySaver | `pipeline_phase` assertions |
| Interrupt/resume lifecycle | 1 | `ainvoke` → `Command(resume=...)` | `__interrupt__` shape assertions |
| Schema validation | 1 | Pydantic model construction | `.model_validate()` assertions |
| Graph compilation | 1 | `compile_team_graph()` | No exception raised |
| Live supervisor routing | 2 | Direct script + LangSmith | Visual trace inspection |
| Multi-agent collaboration quality | 2 | Direct script + LangSmith | Trace node sequence observation |
| Plan quality (LLM judge) | 3 | `langsmith.aevaluate()` | Score threshold (≥ 0.75) |
| E2E task completion | 3 | Superset trajectory match | Score threshold (≥ 0.90) |

---

## 6. Key Imports Reference

```python
# Checkpointer for tests
from langgraph.checkpoint.memory import MemorySaver

# Resume command
from langgraph.types import Command

# Fake LLM for deterministic tests
from langchain_core.language_models.fake import FakeListChatModel

# LangSmith tracing context
import langsmith as ls

# Interrupt error types (documented)
from langgraph.errors import GraphInterrupt, GraphRecursionError

# NOTE: GraphBubbleUp is NOT documented — import with try/except guard (LG-NEW-002)
```

---

*Sources: LangGraph official docs via context7 MCP (`/websites/langchain_oss_python_langgraph`),
LangSmith docs via docs-langchain MCP. All code patterns verified against live MCP query results.*
