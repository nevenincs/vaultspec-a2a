---
title: 'SDD Blackboard Integration — Implementation Derisking Notes'
date: '2026-03-03'
type: research
tags: ['#research', '#sdd-blackboard-integration']
related:
  - '[[2026-03-03-sdd-blackboard-integration-019-teamstate-enrichment]]'
  - '[[2026-03-03-sdd-blackboard-integration-022-contextual-anchoring]]'
---

## sdd-blackboard-integration — implementation derisking notes

**Date:** 2026-03-03
**Feeds into:** ADR-019, ADR-022
**Sources:** LangGraph official docs (context7 `/websites/langchain_oss_python_langgraph`),
LangChain docs MCP (`mcp__docs-langchain`), codebase inspection

---

## 1. ADR-019: LangGraph State Extension Patterns

### 1.1 `NotRequired` Fields in `TypedDict` State

LangGraph supports `NotRequired` fields natively. The official durable-execution
docs use them directly:

```python
from typing import NotRequired
from typing_extensions import TypedDict

class State(TypedDict):
    url: str
    result: NotRequired[str]   # absent until the node sets it
```python

**Source:** <https://docs.langchain.com/oss/python/langgraph/durable-execution>

Key behaviour:

- When a `NotRequired` key is absent from the graph input, LangGraph treats it
  as absent from state — not as `None`, not as a default value. The channel
  simply does not exist in that checkpoint.
- Node code that reads absent `NotRequired` keys with `state["key"]` will raise
  `KeyError`. Always use `state.get("key")` or `state.get("key", default)`.
- Nodes that return a dict with only a subset of state keys are valid — LangGraph
  only updates the keys that appear in the returned dict. Unmentioned keys are
  unchanged.

**Pitfall:** `NotRequired` is from `typing` in Python 3.11+ and from
`typing_extensions` in earlier versions. The project uses Python 3.13 so
`from typing import NotRequired` is correct. Do not import from
`typing_extensions` in new code (ADR-002 constraint).

### 1.2 `Annotated` Reducer Wiring — Exact Syntax

```python
from typing import Annotated
from typing_extensions import TypedDict
import operator

class State(TypedDict):
    # Plain append via operator.add:
    bar: Annotated[list[str], operator.add]

    # Custom reducer function:
    vault_index: Annotated[dict[str, list[str]], _merge_vault_index]

    # LangGraph built-in:
    messages: Annotated[list[BaseMessage], add_messages]
```text

**Source:** <https://docs.langchain.com/oss/python/langgraph/use-graph-api>,
<https://docs.langchain.com/oss/python/langgraph/graph-api>

Reducer function signature:

```python
def _merge_vault_index(
    existing: dict[str, list[str]],   # current state value
    new: dict[str, list[str]],         # value returned by node
) -> dict[str, list[str]]:             # new state value
    ...
```text

LangGraph calls `reducer(existing_value, node_return_value)` on every state
update where the key appears in the node's return dict. The reducer's return
value becomes the new channel value stored in the checkpoint.

**Coexistence with `add_messages`:** Multiple `Annotated` fields with different
reducers on the same `TypedDict` are fully supported. Each key's reducer is
independent. `add_messages` on `messages` and `_merge_vault_index` on
`vault_index` operate in isolation — there is no interference.

**Pitfall — reducer called with empty initial value:** When a node first writes
to an `Annotated` key that has never been set, the `existing` argument is the
channel's default value. For `dict` channels the default is `{}`, for `list`
channels it is `[]`. **The reducer must handle these zero values gracefully.**
`_merge_vault_index({}, {"adr": ["path/to/file.md"]})` must return
`{"adr": ["path/to/file.md"]}` correctly.

**Pitfall — `NotRequired` + `Annotated` combination:** As of LangGraph 0.2+,
`NotRequired[Annotated[T, reducer]]` is not valid Python typing syntax. The
correct approach is plain `Annotated[T, reducer]` without `NotRequired` wrapping
when a reducer is present, and `NotRequired[T]` without `Annotated` wrapping for
scalar last-write-wins fields. This is because `Annotated` already carries the
semantics of "this key is managed by a reducer" which implies it must be present
(the reducer is always called). For `vault_index` and `validation_errors` (both
reducer-managed), omit `NotRequired`. For `active_feature` and `pipeline_phase`
(scalar, last-write-wins), `NotRequired[str | None]` is correct.

### 1.3 Checkpoint Serialization for `NotRequired` Fields

The `AsyncSqliteSaver` (via `langgraph-checkpoint-sqlite`) serializes graph state
using `JsonPlusSerializer` from `langgraph-checkpoint`. This serializer:

- Handles Python primitives (dict, list, str, int, bool, None).
- Handles `BaseMessage` subclasses, datetimes, enums, and LangGraph/LangChain
  primitives natively.
- Serializes only the keys that are **present** in state — absent `NotRequired`
  keys produce no entry in the checkpoint blob.

**Source:** <https://docs.langchain.com/oss/python/langgraph/persistence>

**Critical constraint:** All values stored in `TeamState` must be
JSON-serializable primitives (dicts, lists, strings, numbers, booleans).
`vault_index: dict[str, list[str]]` and `validation_errors: list[str]` satisfy
this. Storing `Path` objects, `ContextRef` Pydantic models, or any non-primitive
in these fields would cause a serialization error at checkpoint time.

**Source:** <https://docs.langchain.com/oss/python/langgraph/functional-api>

> "Use python primitives like dictionaries, lists, strings, numbers, and
> booleans to ensure that your inputs and outputs are serializable."

**Missing key behaviour on deserialization:** When a checkpoint is loaded that
was created before the new fields were added, `JsonPlusSerializer` simply
produces a state dict that lacks the new keys. Nodes reading `state.get("active_feature")`
will receive `None`. Nodes reading `state["vault_index"]` will raise `KeyError`.
This is why ADR-019 mandates `state.get()` for all four new fields.

### 1.4 Initial State Patch — Passing Alongside `graph_input`

LangGraph's `graph.ainvoke(input, config)` accepts any dict matching the state
schema as `input`. Additional keys are merged into the initial state before the
first node runs:

```python
# All four new fields always present in graph_input:
graph_input: dict[str, Any] = {
    "messages": [SystemMessage(content=preamble), HumanMessage(content=body.initial_message)],
    "active_feature": metadata.feature_tag if metadata else None,
    "pipeline_phase": None,
    "vault_index": _build_initial_vault_index(workspace_root, metadata.feature_tag)
                   if metadata and metadata.feature_tag else {},
    "validation_errors": [],
    # existing required fields:
    "thread_id": thread_id,
    "active_agent": "",
    "artifacts": [],
    "current_plan": [],
    "token_usage": {},
}
result = await graph.ainvoke(graph_input, config={"configurable": {"thread_id": thread_id}})
```text

LangGraph applies reducers to the initial input values exactly as it does for
node return values. For `Annotated` fields, the reducer is called with
`(default_value, initial_input_value)`. For `vault_index`:
`_merge_vault_index({}, initial_vault_index)` — the reducer must handle `{}` as
`existing`.

**Pitfall — `thread_id` in config vs state:** LangGraph uses
`config["configurable"]["thread_id"]` for checkpointer routing. The `thread_id`
field in `TeamState` is our application-level identifier. Both must be set; they
are independent.

---

## 2. ADR-022: Node Return Conventions, SystemMessage Injection, Conditional Edges

### 2.1 Node Return Conventions

A LangGraph node returns a `dict[str, Any]` where keys are a subset of the state
schema. LangGraph applies each key's reducer (or last-write-wins default) to
produce the updated state:

```python
async def supervisor_node(state: TeamState) -> dict[str, Any]:
    # Returning only the keys being updated — other keys unchanged:
    return {"next": "worker_a"}

    # Returning multiple keys:
    return {
        "next": "worker_a",
        "routing_error": None,
        "pipeline_phase": "plan",
    }

    # Returning a reducer-managed key — reducer is applied:
    return {
        "validation_errors": ["frontmatter missing required field: related"],
    }
    # → _append_validation_errors(existing_errors, ["frontmatter..."]) is called
```text

**Source:** <https://docs.langchain.com/oss/python/langgraph/use-graph-api>

Keys not present in the returned dict are **not touched** — their existing values
are preserved in state. There is no need to return the full state.

**Pitfall — returning `None` for a key clears it for non-reducer fields:**
Returning `{"pipeline_phase": None}` sets `pipeline_phase` to `None` in state
(last-write-wins). For reducer-managed fields, returning `{"validation_errors": []}`
triggers `_append_validation_errors(existing, [])` which returns `[]` (the clear
semantics). Be deliberate.

### 2.2 SystemMessage Injection at Invocation Time (Not Stored in State)

The pattern for prepending ephemeral `SystemMessage` objects at invocation time
without storing them in `state["messages"]`:

```python
async def supervisor_node(state: TeamState) -> dict[str, Any]:
    working_state = compact_context(state, CONTEXT_LIMIT) if should_compact(...) else state

    # Build ephemeral anchoring summary — not stored in state:
    anchoring = _build_anchoring_context(state)

    # Construct the message list for this invocation only:
    messages: list[BaseMessage] = [SystemMessage(content=full_prompt)]
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    messages.extend(working_state.get("messages", []))

    # Pass constructed list to model — NOT returned to state:
    response = await model.ainvoke(messages)

    # Only the routing decision is returned to state:
    return {"next": next_route}
```text

The constructed `messages` list is **never returned** — it is local to the node
invocation. `state["messages"]` is untouched by this node. The `add_messages`
reducer only runs when a node explicitly returns `{"messages": [...]}`.

**Pitfall — SystemMessage IDs and `add_messages` deduplication:** `add_messages`
deduplicates by message `id`. If a `SystemMessage` is constructed without an
explicit `id`, LangChain assigns a UUID at construction time. Since the anchoring
`SystemMessage` is never returned to state, this is not an issue — it only
matters if messages are returned for storage.

**Pitfall — `compact_context` and leading SystemMessages:** The project's
`compact_context()` (`src/vaultspec_a2a/core/context.py`) preserves all leading `SystemMessage`
instances before the first non-system message (ADR-014 §5). The anchoring
`SystemMessage` is constructed fresh per-invocation and never enters
`state["messages"]`, so it is unaffected by compaction. No code change needed
in `compact_context`.

### 2.3 Conditional Edges — Exact API

```python
# Signature:
builder.add_conditional_edges(
    source_node: str,
    path: Callable[[State], str | list[str]],
    path_map: dict[str, str] | None = None,
)
```text

The `path` function receives the **full current state** after the source node
has run and its return values have been merged. It returns the name of the next
node (or `END`).

**Current supervisor routing (existing code):**

```python
route_map: dict[str, str] = {wid: wid for wid in compiled_worker_ids}
route_map["FINISH"] = END
builder.add_conditional_edges(
    "supervisor",
    lambda state: state["next"],  # reads state["next"] set by supervisor_node
    route_map,
)
```text

**Source:** <https://docs.langchain.com/oss/python/langgraph/use-graph-api>

The validation error gate in ADR-022 is implemented **inside `supervisor_node`**
(before returning `{"next": ...}`), not in the conditional edge function. This
is correct — the gate is a node-level concern, not a graph-topology concern. The
conditional edge remains a pure passthrough of `state["next"]`.

**Alternative — gate in the edge function:**

```python
def route_with_error_gate(state: TeamState) -> str:
    if state["next"] == "FINISH" and state.get("validation_errors"):
        return workers[0]   # redirect
    return state["next"]

builder.add_conditional_edges("supervisor", route_with_error_gate, route_map)
```text

This is also valid. Implementing in the edge avoids mutating `routing_error`
state from within `supervisor_node`. **Recommendation:** keep the gate inside
`supervisor_node` so the `routing_error` field is set for observability. The
edge-function approach cannot update state.

**Pitfall — `path_map` must cover all possible return values:** If
`route_with_error_gate` can return `workers[0]` but `workers[0]` is not in
`route_map`, LangGraph raises a `ValueError` at runtime. Ensure the route map
covers all possible outputs of the path function. Since `workers[0]` is already
in `route_map` (it is a valid worker ID), this is safe.

### 2.4 `_build_supervisor_prompt()` Template Replacement

Current implementation (`src/vaultspec_a2a/core/graph.py:169`):

```python
def _build_supervisor_prompt(
    resolved_agents: list[AgentConfig],
    base_prompt: str,
    directive: str | None = None,
) -> str:
    roster = "\n".join(
        f"- {cfg.display_name} ({cfg.id}): {cfg.description.strip()}"
        for cfg in resolved_agents
    )
    if "{{AGENT_ROSTER}}" in base_prompt:
        result = base_prompt.replace("{{AGENT_ROSTER}}", roster)
    else:
        result = base_prompt + f"\n\nYour team members:\n{roster}"
    if directive:
        result = result + f"\n\n## Team Directive\n\n{directive.strip()}"
    return result
```yaml

The ADR-022 extension adds `feature_context: str | None = None` following the
same pattern:

```python
def _build_supervisor_prompt(
    resolved_agents: list[AgentConfig],
    base_prompt: str,
    directive: str | None = None,
    feature_context: str | None = None,   # NEW
) -> str:
    # ... existing AGENT_ROSTER logic ...
    if feature_context:
        if "{{FEATURE_CONTEXT}}" in result:
            result = result.replace("{{FEATURE_CONTEXT}}", feature_context)
        else:
            result = result + f"\n\n## Feature Context\n\n{feature_context}"
    return result
```text

**Call site in `_compile_star()`** (`graph.py:357`):

```python
supervisor_prompt = _build_supervisor_prompt(
    resolved_agents,
    supervisor_agent_config.persona.system_prompt,
    directive=team_config.persona.directive,
    feature_context=f"Active feature: {feature_tag}" if feature_tag else None,
)
```text

`feature_tag` is available at compile time if passed as a parameter to
`compile_team_graph()`. The compile-time block is static (feature tag only).
The dynamic per-invocation context (phase, vault paths, errors) is built by
`_build_anchoring_context(state)` inside `supervisor_node`.

**Pitfall — TOML system prompts and `{{FEATURE_CONTEXT}}`:** ADR-012 §5 states
system prompts in TOML are loaded verbatim. A supervisor TOML that contains the
literal string `{{FEATURE_CONTEXT}}` will have it replaced at graph compile time
by `_build_supervisor_prompt`. This is intentional and consistent with how
`{{AGENT_ROSTER}}` works. Preset authors who do not include the placeholder
receive the feature context appended at the end of the prompt instead.

---

## 3. Interaction Between `add_messages` and Custom Reducers

`add_messages` is a specialized reducer that:

1. Appends new messages by default.
2. Deduplicates by message `id` (updates existing message if same `id`).
3. Handles `RemoveMessage` objects to delete specific messages by id.

Custom reducers on other keys (`_merge_vault_index`, `_append_validation_errors`)
are completely independent. LangGraph applies reducers per-key in the returned
dict — there is no cross-key interaction.

**The only ordering concern:** if a node returns both `messages` and
`validation_errors`, both reducers run in the same state update (same
"super-step"). The order of reducer application within a single update is
deterministic (alphabetical by key name in the current implementation) but
should not be relied upon since individual reducers are independent.

---

## 4. Known Pitfalls Summary

| Pitfall                                           | Context                                       | Mitigation                                                                               |
| ------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `NotRequired` + `Annotated` invalid syntax        | `NotRequired[Annotated[T, fn]]` does not work | Use `Annotated[T, fn]` for reducer fields; `NotRequired[T]` for scalar fields only       |
| `KeyError` on absent `NotRequired` keys           | Old checkpoints lack new keys                 | Use `state.get("field", default)` for all `NotRequired` fields                           |
| Reducer called with empty default                 | First write to `Annotated` field              | Reducer must handle `{}` / `[]` as `existing` argument                                   |
| Non-primitive values in state                     | Storing `Path`, Pydantic models, etc.         | Only store `str`, `int`, `bool`, `dict`, `list` — convert `Path` to `str` before storing |
| Anchoring `SystemMessage` entering `add_messages` | Accidentally returning anchoring message      | Never return the ephemeral anchoring list to state; return only routing/metadata keys    |
| Route map missing gate-redirect target            | `workers[0]` not in `route_map`               | Verify all possible path-function return values exist in `route_map`                     |
| `compact_context` removing vault preamble         | ADR-014 preamble compressed                   | Per-invocation `_build_anchoring_context` is immune; reconstructed fresh each call       |
| `JsonPlusSerializer` failing on custom types      | Non-JSON-serializable state values            | `vault_index` paths must be `str`, not `Path`; `validation_errors` must be `list[str]`   |

---

## Sources

- [LangGraph use-graph-api (Python)](https://docs.langchain.com/oss/python/langgraph/use-graph-api) — reducers, `Annotated`, node return conventions
- [LangGraph graph-api (Python)](https://docs.langchain.com/oss/python/langgraph/graph-api) — `add_conditional_edges`, default reducer
- [LangGraph durable-execution (Python)](https://docs.langchain.com/oss/python/langgraph/durable-execution) — `NotRequired` fields in `TypedDict`
- [LangGraph persistence (Python)](https://docs.langchain.com/oss/python/langgraph/persistence) — `AsyncSqliteSaver`, `JsonPlusSerializer`, checkpoint libraries
- [LangGraph functional-api serialization](https://docs.langchain.com/oss/python/langgraph/functional-api) — JSON-serializable constraint
- [LangGraph quickstart (Python)](https://docs.langchain.com/oss/python/langgraph/quickstart) — conditional edge functions, `should_continue` pattern
