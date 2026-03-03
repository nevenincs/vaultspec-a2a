---
title: "Gap Analysis: Current A2A Engine vs. SDD Blackboard Integration Mandate"
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: "Precise code-level gap analysis comparing the current lib/core implementation against the four SDD blackboard mandate areas."
---

# Gap Analysis: Current A2A Engine vs. SDD Blackboard Integration Mandate

**Date:** 2026-03-03
**Feature tag:** `#sdd-blackboard-integration`
**Reference:** `docs/research/2026-03-02-sdd-blackboard-architecture-research.md`
**Scope:** `lib/core/state.py`, `lib/core/nodes/worker.py`, `lib/core/nodes/supervisor.py`, `lib/core/graph.py`, `lib/core/team_config.py`, `lib/core/metadata.py`, `lib/core/preamble.py`, `lib/core/context.py`

---

## 1. State Disconnect Gap

### What `TeamState` currently has

**File:** `lib/core/state.py:72–111`

```python
class TeamState(TypedDict):
    active_agent: str                                         # line 81
    artifacts: Annotated[list[dict[str, str]], ...]          # line 84
    current_plan: Annotated[list[dict[str, str]], ...]       # line 87
    loop_count: NotRequired[int]                             # line 98
    messages: Annotated[list[BaseMessage], add_messages]     # line 101
    next: NotRequired[str]                                   # line 102
    routing_error: NotRequired[str]                          # line 105
    thread_id: str                                           # line 108
    token_usage: Annotated[dict[str, dict[str, int]], ...]   # line 111
```

The `artifacts` field (line 84) stores in-memory `dict[str, str]` records — not pointers to physical `.vault/` files. The `current_plan` field (line 87) stores a plain list of dicts, not references to a `.vault/plan/` markdown file. There is no field tracking which feature is active, what phase the pipeline is in, or a live index of physical `.vault/` documents.

### What is missing

| Missing field | Type (per mandate) | Purpose |
|---|---|---|
| `active_feature` | `NotRequired[str]` | The feature tag (e.g. `"editor-demo"`) that is the central glue binding all `.vault/` artifacts |
| `pipeline_phase` | `NotRequired[str]` | One of `"research"`, `"specify"`, `"plan"`, `"execute"`, `"verify"` — the supervisor uses this for contextual anchoring |
| `vault_index` | `dict[str, str]` | Mapping of wikilink (`[[adr-018]]`) → physical `.vault/` file path; acts as the in-memory representation of the blackboard |
| `validation_errors` | `list[str]` | Populated when an agent writes a malformed artifact (wrong frontmatter, missing `related:` fields); surfaces quality gate failures to the supervisor |

### Partial existing bridge

`lib/core/metadata.py` (`ThreadMetadata`, line 51) and `lib/core/preamble.py` (`build_context_preamble`, line 19) implement `feature_tag` and `context_refs` at the **thread creation layer** (ADR-014). The preamble is injected as a `SystemMessage` once at thread start (line 46–56 of `preamble.py`). However:

- `feature_tag` and `context_refs` live on `ThreadMetadata`, a Pydantic model created at the API endpoint, **not on `TeamState`**. The graph itself is completely unaware of them after the initial preamble injection.
- `discover_context_refs` (`metadata.py:89`) scans `.vault/` for matching files but the results are only used to compose a text message — they are never structured into a `vault_index` dict that nodes can query programmatically.
- `context_refs` in the preamble tell agents documents *exist* but do not read and inject the file content. The research mandate requires content injection (see Gap 2 below).

---

## 2. Context Dilution Gap

### How workers currently receive context

**File:** `lib/core/nodes/worker.py:126–137`

```python
async def worker_node(state: TeamState) -> dict[str, Any]:
    working_state = (
        compact_context(state, CONTEXT_LIMIT)
        if should_compact(state, CONTEXT_LIMIT)
        else state
    )
    messages = [SystemMessage(content=system_prompt), *working_state["messages"]]
```

The message list passed to the LLM is constructed at `worker.py:137`:
1. `SystemMessage(content=system_prompt)` — the agent's static persona from the TOML `[agent.persona] system_prompt` field.
2. `*working_state["messages"]` — the full (or compacted) conversation history.

There is no step where `.vault/` document content is read from disk and injected into the context. The `compact_context` function (`context.py:62`) replaces mid-history messages with a generic summary placeholder (`context.py:113–118`) but preserves chat messages, not grounding documents.

### Where context construction lives (precise lines)

| Location | What happens |
|---|---|
| `worker.py:132–136` | Optional context compaction check |
| `worker.py:137` | `messages` list built: `[SystemMessage(system_prompt), *history]` |
| `worker.py:165` | `effective_model.ainvoke(messages)` — only argument is the message list |
| `context.py:62–125` | `compact_context()` — trims history, inserts a synthetic summary, returns pruned state |
| `preamble.py:19–56` | `build_context_preamble()` — builds a metadata SystemMessage injected once at thread start (not per node invocation) |

### Where SDD document injection would go

The correct insertion point is `worker.py` between lines 136 and 137 — after the compaction decision and before `messages` is finalised. Concretely:

```
# INJECT HERE: resolve state["active_feature"] + state["vault_index"]
# → read physical .vault/ files for the current feature
# → prepend as read-only SystemMessage blocks (highest-priority context)
# → THEN append working_state["messages"] (compacted history)
```

This would require:
1. `TeamState` having `active_feature` and `vault_index` (Gap 1).
2. A new utility function (analogous to `discover_context_refs` in `metadata.py`) that reads file content, not just paths.
3. The mount step producing one or more `SystemMessage` objects with the raw `.vault/` markdown.

---

## 3. Orchestration Gap

### How the supervisor currently routes

**File:** `lib/core/nodes/supervisor.py:29–110`

The supervisor is created via `create_supervisor_node(model, system_prompt, workers)` (line 29). It operates as follows:

1. **Input:** The full (or compacted) `state["messages"]` list — conversational history only (`supervisor.py:61`).
2. **Decision:** Appends routing instructions to the system prompt (`supervisor.py:47–52`): `"Based on the conversation, who should act next?"`.
3. **Output:** A plain string matched against `[*workers, "FINISH"]` (`supervisor.py:84–90`). Result stored in `state["next"]`.

The routing decision is grounded in **nothing but conversational text**. The supervisor does not inspect:
- Which feature is active (`active_feature`).
- What pipeline phase is current (`pipeline_phase`).
- Which `.vault/` binding documents exist for the feature (no vault_index lookup).
- Whether the previous worker produced a well-formed artifact (no `validation_errors` awareness).

### Where feature-lifecycle-aware routing would be added

**File:** `lib/core/nodes/supervisor.py:54–106` (the `supervisor_node` closure)

The supervisor would need to:
1. Read `state["active_feature"]` and `state["pipeline_phase"]` (requires Gap 1 to be filled).
2. Retrieve the vault index for the active feature to know which binding documents exist.
3. Inject a structured "Feature Context Block" as an additional `SystemMessage` immediately before the routing call (`supervisor.py:61`), listing the active phase and anchoring documents.
4. Optionally modify the routing_instructions (`supervisor.py:47–52`) to constrain options to phase-appropriate workers.

The `_build_supervisor_prompt` function (`graph.py:169–191`) already handles prompt injection via `{{AGENT_ROSTER}}` replacement. An analogous `{{FEATURE_CONTEXT}}` placeholder mechanism could be added there for compile-time phase awareness, but the runtime state-dependent anchoring must happen inside the `supervisor_node` closure.

### Star topology routing (graph.py)

**File:** `lib/core/graph.py:409–415`

```python
route_map: dict[str, str] = {wid: wid for wid in compiled_worker_ids}
route_map["FINISH"] = END
builder.add_conditional_edges(
    "supervisor",
    lambda state: state["next"],
    route_map,
)
```

The conditional edge at `graph.py:412–415` is a pure passthrough of `state["next"]`. There is no verifier intercept, no phase-gate, and no back-edge to a quality-check node. Adding a verifier loop would require a new conditional branch here.

---

## 4. Task Tracking Gap

### Current task queue mechanism

There is **no task queue** in the current implementation. The closest approximations are:

| Mechanism | File | Description | Limitation |
|---|---|---|---|
| `current_plan` | `state.py:87` | `list[dict[str, str]]` with `_replace_plan` reducer | Full-replacement on each cycle; no sequential numbering; purely in-memory; lost on compaction |
| `loop_count` | `state.py:98–98` | Integer incremented by `_wrap_loop_node` | Only tracks loop iterations for `pipeline_loop` topology; not a task queue |
| `next` | `state.py:102` | String: the next route name | Routing signal only; no task identity |
| `artifacts` | `state.py:84` | Append-only list of `dict[str, str]` with dedup by `id` | Records completed artifact outputs; no notion of pending/in-progress tasks |

There is no sequential tag system (e.g., `SBI-001`), no disk-persisted task queue file, and no mechanism for the orchestrator to determine "what is the next task" across session restarts. When the SQLite checkpointer saves `TeamState`, the `current_plan` list is persisted, but it stores arbitrary dicts with no enforced schema for task status tracking.

### What `context_refs` provides (partial overlap)

`metadata.py:89–133` (`discover_context_refs`) can scan `.vault/` for files by stage pattern. The `ContextRef` model (`metadata.py:34–48`) carries `path`, `stage`, and `summary`. This is the closest existing infrastructure to a "vault index" but:
- It lists documents as pointers — it does not parse plan documents to extract structured task lists.
- It runs once at thread creation, not dynamically during graph execution.
- Results do not feed back into `TeamState` during a run.

### What is needed

Per the mandate:
1. **Task schema:** A new in-state structure (or standalone TypedDict) with fields: `task_id` (e.g. `SBI-001`), `title`, `status` (`pending`/`in_progress`/`done`), `feature_tag`, `exec_artifact_path`.
2. **Disk persistence layer:** A `.vault/plan/yyyy-mm-dd-{feature}-queue.md` file read at graph start and written on each task transition. The orchestrator reads this file to reconstruct queue state after a context flush or session restart.
3. **`TeamState` integration:** A new `task_queue: list[dict[str, str]]` field (with an appropriate reducer) and `active_task_id: NotRequired[str]` so nodes can identify the current work unit without parsing chat history.

---

## Summary Table

| Gap Area | Current State | Missing | Primary Insertion Point |
|---|---|---|---|
| **State Disconnect** | `TeamState` has `active_agent`, `artifacts`, `current_plan`, `messages` | `active_feature`, `pipeline_phase`, `vault_index`, `validation_errors` | `lib/core/state.py:72` — add 4 new `NotRequired` fields |
| **Context Dilution** | `worker.py:137` builds `[SystemMessage(prompt), *history]` | Blackboard mount step reading `.vault/` file content for active feature | `lib/core/nodes/worker.py:136–137` — inject between compaction and `ainvoke` |
| **Orchestration Gap** | Supervisor routes purely on conversation text (`supervisor.py:61`) | Feature-lifecycle context block injection; phase-aware routing instructions | `lib/core/nodes/supervisor.py:61` + conditional edge at `graph.py:412–415` |
| **Task Tracking Gap** | No task queue; `current_plan` is an unstructured, ephemeral in-memory list | Sequential task IDs, status tracking, disk-persisted queue file | New `task_queue` + `active_task_id` fields in `state.py`; new queue reader/writer utility |

---

## Key Positive Finding

The `metadata.py` + `preamble.py` infrastructure from ADR-014 provides a genuine partial foundation:
- `discover_context_refs` already does feature-tag-scoped `.vault/` scanning.
- `build_context_preamble` already injects a `SystemMessage` with the document listing.
- `feature_tag` is already accepted at the API layer.

The gap is that this runs **once at thread start** as a pointer-only listing, not per-node-invocation content injection. The bridge from "list of paths" to "content mounted into context" and the integration of that context into `TeamState` as a queryable `vault_index` are the core missing pieces.
