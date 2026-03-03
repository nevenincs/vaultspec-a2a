---
adr_id: 022
title: Contextual Anchoring in Graph Lifecycle
date: 2026-03-03
status: Proposed
related:
  - docs/adrs/013-team-composition-topology.md
  - docs/adrs/014-thread-metadata-context-injection.md
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
---

# ADR-022: Contextual Anchoring in Graph Lifecycle

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

ADR-014 established a one-time context preamble injected at thread creation ---
a `SystemMessage` listing the feature tag and available `.vault/` document
paths. ADR-019 extended `TeamState` to carry `active_feature`, `pipeline_phase`,
`vault_index`, and `validation_errors` as required, always-present fields.

The remaining gap is **per-invocation contextual anchoring**: ensuring that on
every supervisor routing call and every worker invocation, the active feature
context is surfaced as a structured, high-priority signal rather than buried in
a growing conversation history. Three concrete problems motivate this ADR:

| Problem | Evidence |
| --- | --- |
| **Supervisor routes on conversation text alone** | `supervisor.py:61` builds `messages = [SystemMessage(full_prompt), *history]`. The routing decision is grounded in conversational history with no structured feature/phase signal. Routing is unreliable when history is long or compacted. |
| **No validation error gate** | The supervisor returns `FINISH` even when `state["validation_errors"]` is non-empty. Malformed artifacts propagate silently. |
| **Worker context dilution** | Workers receive `[SystemMessage(persona), *history]`. As history grows and compaction replaces mid-history content with summaries, the feature context from the ADR-014 preamble may be compressed or lost. Workers have no per-invocation reminder of which feature they are working on. |

### 1.1 What This ADR Does Not Do

This ADR explicitly does **not**:

- Inject `.vault/` file content into any prompt. Content injection is scoped
  to ADR-020 (blackboard mount step, deferred). This ADR injects only the
  feature tag, pipeline phase, and a list of relevant vault doc paths ---
  metadata only.
- Modify the TOML system prompt format. ADR-012 S5 prohibits template
  interpolation in TOML system prompts for v1. All anchoring is implemented
  as additional `SystemMessage` objects prepended at invocation time, not as
  TOML modifications.
- Implement phase-based worker filtering. The supervisor gains awareness of
  validation errors but the routing option set remains unchanged; phase-based
  worker filtering is deferred.

### 1.2 Prior Art

**Blackboard control unit pattern** (arXiv 2507.01701): The control unit in a
blackboard architecture "selects which agents should act in each iteration based
on the query and current blackboard state." Per-invocation state inspection is
canonical --- the control unit does not rely solely on conversation history.

**Codified Context trigger tables** (arXiv 2602.20478): Production AI
infrastructure automatically routes tasks to specialized agents based on file
patterns and domain context. "Trigger tables encode which domain expertise each
file area requires." The `{{FEATURE_CONTEXT}}` block in the supervisor prompt
serves this function --- it encodes which phase-relevant context is available.

**Contextual anchoring directives** (contextpatterns.com): Grounding alone does
not guarantee the model uses retrieved information. Explicit anchoring
instructions (`[PRIMARY reference, do not contradict]`) are required. This is
not optional --- retrieval without anchoring is known to allow models to fall back
to training data even when relevant documents are provided.

**Google ADK --- context as compiled view**: "Context is a compiled view over a
richer stateful system, rebuilt fresh each invocation." The anchoring summary
produced by `_build_anchoring_context()` below is exactly this --- a fresh
compilation of the state's feature fields into a structured SystemMessage,
rebuilt on every node call.

## 2. Decision

### 2.1 `{{FEATURE_CONTEXT}}` Placeholder in `_build_supervisor_prompt()`

`_build_supervisor_prompt()` (`lib/core/graph.py:169`) is extended to accept an
optional `feature_context: str | None = None` parameter. When provided, it
replaces a `{{FEATURE_CONTEXT}}` placeholder in the base prompt (analogous to
the existing `{{AGENT_ROSTER}}` mechanism):

```python
def _build_supervisor_prompt(
    resolved_agents: list[AgentConfig],
    base_prompt: str,
    directive: str | None = None,
    feature_context: str | None = None,   # NEW (ADR-022)
) -> str:
    # ... existing AGENT_ROSTER logic unchanged ...
    if feature_context:
        if "{{FEATURE_CONTEXT}}" in result:
            result = result.replace("{{FEATURE_CONTEXT}}", feature_context)
        else:
            result = result + f"\n\n## Feature Context\n\n{feature_context}"
    return result
```

The compile-time `feature_context` block is a static string describing the
feature tag at graph compilation time. Dynamic, per-invocation context (phase,
vault paths, validation errors) is handled by `_build_anchoring_context()` (S2.2).

### 2.2 `_build_anchoring_context()` --- Per-Invocation Anchoring Summary

A new function in `lib/core/nodes/supervisor.py` and `lib/core/nodes/worker.py`
(or a shared utility in `lib/core/anchoring.py`):

```python
_ANCHOR_PATH_CAP = 10  # max vault paths per doc-type in the summary

def _build_anchoring_context(state: TeamState) -> str | None:
    """Produce a per-invocation anchoring summary from TeamState.

    Returns None when active_feature is None (no feature bound to this thread),
    so anchoring is skipped for threads that have no active SDD feature.

    The summary includes:
    - Active feature tag
    - Current pipeline phase (if set)
    - List of vault doc paths by type (from vault_index), capped per doc-type
    - Count of active validation errors (if any)

    Does NOT read file content. Paths only.
    """
    feature = state["active_feature"]
    if not feature:
        return None

    lines: list[str] = [
        "## Active Feature Context",
        f"- **Feature:** {feature}",
    ]

    phase = state["pipeline_phase"]
    if phase:
        lines.append(f"- **Phase:** {phase}")

    vault_index: dict[str, list[str]] = state["vault_index"]
    if vault_index:
        lines.append("\n### Available Vault Documents")
        lines.append(
            "The following documents exist for this feature. "
            "Read them as needed using your filesystem capabilities."
        )
        for doc_type, paths in vault_index.items():
            lines.append(f"\n**{doc_type.upper()}**")
            visible = paths[:_ANCHOR_PATH_CAP]
            for p in visible:
                lines.append(f"  - `{p}`")
            remainder = len(paths) - len(visible)
            if remainder > 0:
                lines.append(f"  - (+ {remainder} more)")

    errors: list[str] = state["validation_errors"]
    if errors:
        lines.append(f"\n### Validation Errors ({len(errors)} active)")
        for err in errors:
            lines.append(f"  - {err}")

    return "\n".join(lines)
```

**Token budget:** A typical anchoring summary with one feature tag, one phase,
five vault paths across three doc-types, and zero errors produces approximately
200--280 tokens. With ten vault paths and two validation errors: approximately
350--420 tokens. This is well within the budget for any model tier.

### 2.3 Supervisor Node: Anchoring Integration

`create_supervisor_node()` (`lib/core/nodes/supervisor.py:29`) is amended to
inject the anchoring summary as an additional `SystemMessage` immediately before
the routing call:

```python
async def supervisor_node(state: TeamState) -> dict[str, Any]:
    working_state = (
        compact_context(state, CONTEXT_LIMIT)
        if should_compact(state, CONTEXT_LIMIT)
        else state
    )

    # Build per-invocation anchoring summary (ADR-022).
    # Returns None when active_feature is None; skipped in that case.
    anchoring = _build_anchoring_context(state)

    messages: list[BaseMessage] = [SystemMessage(content=full_prompt)]
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    messages.extend(working_state["messages"])

    # ... rest of routing logic unchanged ...
```

**Message ordering after this change:**

```text
[1] SystemMessage(content=full_prompt)         <- compiled supervisor prompt (persona + roster)
[2] SystemMessage(content=anchoring_summary)   <- per-invocation feature context (NEW, when active_feature is set)
[3..] *working_state["messages"]               <- compacted conversation history
```

The anchoring summary sits between the supervisor's identity definition and the
conversation history --- higher priority than history but lower than the persona
definition, which is the correct attention ordering for LLM routing.

### 2.4 Validation Error Gate in Supervisor

The supervisor must not route to `FINISH` when `validation_errors` is non-empty.
This is implemented as a guard in `supervisor_node()` after parsing the route:

```python
# After deriving next_route from model response:
if next_route == "FINISH":
    errors = state["validation_errors"]
    if errors:
        _logger.warning(
            "supervisor blocked FINISH: %d validation error(s) active --- "
            "rerouting to first available worker",
            len(errors),
        )
        # Route to the first worker to force error resolution.
        next_route = workers[0] if workers else "FINISH"
        return {
            "next": next_route,
            "routing_error": (
                f"FINISH blocked: {len(errors)} validation error(s) must be resolved first."
            ),
        }
```

This is a fail-closed gate: if the supervisor attempts to finish with unresolved
validation errors, it is redirected to the first worker in the roster. The
routing error is recorded in state for observability.

### 2.5 Worker Node: Anchoring Integration

`create_worker_node()` (`lib/core/nodes/worker.py:92`) is amended to prepend the
anchoring summary between the persona prompt and the conversation history:

```python
async def worker_node(state: TeamState) -> dict[str, Any]:
    working_state = (
        compact_context(state, CONTEXT_LIMIT)
        if should_compact(state, CONTEXT_LIMIT)
        else state
    )

    # Build per-invocation anchoring summary (ADR-022).
    anchoring = _build_anchoring_context(state)

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    messages.extend(working_state["messages"])

    # ... rest of worker logic unchanged ...
```

**Message ordering after this change:**

```text
[1] SystemMessage(content=system_prompt)       <- TOML agent persona
[2] SystemMessage(content=anchoring_summary)   <- per-invocation feature context (NEW, when active_feature is set)
[3..] *working_state["messages"]               <- compacted conversation history
```

This is consistent with the ADR-014 S2.3 ordering principle: role definition >
project context > conversation. The anchoring summary is a dynamic replacement
for the static preamble that may have been compressed away by `compact_context`.

## 3. Consequences

### Positive

- Supervisor routing decisions are grounded in structured feature/phase state,
  not just conversational text. Reliability improves for long-running threads
  where history is compacted.
- The validation error gate prevents silent propagation of malformed artifacts ---
  the supervisor is forced to address errors before declaring completion.
- Workers receive a per-invocation reminder of the active feature and available
  vault documents, compensating for context compaction that may have removed the
  original ADR-014 preamble.
- Token overhead is minimal: ~200--400 tokens per invocation for the anchoring
  summary.
- Node code reads state fields directly with `state["field"]` --- no defensive
  `.get()` patterns.

### Negative / Trade-offs

- The validation error gate redirects to `workers[0]` --- the first worker in the
  roster --- which may not be the correct resolver. Callers can work around this
  by ordering the worker roster so the most appropriate error-resolver is first.
  A more sophisticated routing decision is deferred.
- Injecting two `SystemMessage` objects per node call (persona + anchoring)
  increases the message list length by one for every invocation. This is
  cosmetically visible in debug logs and token counts but has no functional
  impact.
- `_build_anchoring_context()` reads `vault_index` from state on every
  invocation. The `_ANCHOR_PATH_CAP = 10` depth cap per doc-type prevents token
  overflow for large indexes.

## 4. Rejected Alternatives

### Inject Anchoring as a TOML Template Variable

ADR-012 S5 explicitly prohibits template variable interpolation in TOML system
prompts for v1. The per-invocation nature of the anchoring summary (it changes
as `vault_index` and `validation_errors` change) also makes compile-time
template injection incorrect --- the anchor must reflect the current state at each
node call, not the state at graph compilation. Rejected.

### Modify the Existing Context Preamble Instead of Adding a New SystemMessage

The ADR-014 context preamble in `state["messages"]` persists in the
checkpointer as a regular message. Modifying it on each invocation would require
identifying and replacing the preamble message in the message list --- a fragile
operation that interacts poorly with `add_messages` semantics (LangGraph's
message reducer deduplicates by ID). A separate, freshly-constructed
`SystemMessage` prepended at invocation time is the correct approach. Rejected.

### Filter Workers by Pipeline Phase at Routing Time

The supervisor could restrict the `options` list to workers appropriate for the
current `pipeline_phase`. Deferred because: (a) phase-to-worker mapping requires
additional TOML schema; (b) the anchoring summary already communicates the phase
to the supervisor's LLM, which can self-enforce the constraint; (c) hard
filtering reduces flexibility for teams with workers that span phases.

### Implement `_build_anchoring_context` as a LangGraph Node

A dedicated "anchoring node" could update `TeamState` with a pre-compiled
anchoring string on each cycle. Rejected because: (a) it adds a node to the
graph for a pure computation with no I/O; (b) the anchoring string is
intentionally ephemeral --- not stored in state, only used at invocation time;
(c) inline computation is simpler and consistent with how `compact_context` is
implemented.

## 5. Implementation Constraints

- `_build_anchoring_context()` returns `None` only when `state["active_feature"]`
  is `None` (no feature bound). It never returns `None` due to a missing key.
  Calling nodes check `if anchoring:` to skip injection when no feature is set.
- The validation error gate must be tested with a state that has
  `validation_errors` non-empty and `next_route == "FINISH"` --- verify that the
  gate redirects to `workers[0]` and sets `routing_error`.
- `_build_anchoring_context()` applies `_ANCHOR_PATH_CAP = 10` per doc-type.
  When more paths are present, include a `(+ N more)` note.
- `_build_anchoring_context()` must not read any files from disk. It operates
  on `state["vault_index"]` (paths only). File content injection is strictly
  scoped to ADR-020.
- Both `supervisor_node` and `worker_node` insert the anchoring `SystemMessage`
  at position `[1]` (after persona, before history).
- `pipeline_phase` valid values mirror the six `.vault/` directory tags:
  `"research"`, `"reference"`, `"adr"`, `"plan"`, `"exec"`, `"audit"`
  (per `vaultspec-documentation.builtin.md`).

## 6. Module Hierarchy Impact

```text
lib/core/
  state.py            UNCHANGED (fields added by ADR-019)
  graph.py            AMENDED: _build_supervisor_prompt() gains
                      feature_context param and {{FEATURE_CONTEXT}} support
  nodes/
    supervisor.py     AMENDED: supervisor_node() injects anchoring summary;
                      adds validation_errors FINISH gate;
                      new _build_anchoring_context() (or imported from shared)
    worker.py         AMENDED: worker_node() injects anchoring summary
  tests/
    test_graph.py          AMENDED: _build_supervisor_prompt feature_context tests
    test_anchoring.py      NEW: _build_anchoring_context unit tests (all branches)
    test_supervisor.py     AMENDED: validation error gate test
```

## 7. References

- `lib/core/nodes/supervisor.py:29` --- `create_supervisor_node()` (to be amended)
- `lib/core/nodes/supervisor.py:54` --- `supervisor_node()` closure (routing logic)
- `lib/core/nodes/worker.py:92` --- `create_worker_node()` (to be amended)
- `lib/core/nodes/worker.py:126` --- `worker_node()` closure (message construction)
- `lib/core/graph.py:169` --- `_build_supervisor_prompt()` (gains feature_context param)
- `lib/core/graph.py:409` --- `add_conditional_edges` for supervisor routing
- [ADR-013](013-team-composition-topology.md) --- Team Composition (supervisor routing, `state["next"]`)
- [ADR-014](014-thread-metadata-context-injection.md) --- Thread Metadata (context preamble, message ordering)
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) --- TeamState enrichment (active_feature, vault_index, validation_errors)
- [arXiv 2507.01701](https://arxiv.org/abs/2507.01701) --- Blackboard control unit per-invocation state inspection
- [arXiv 2602.20478](https://arxiv.org/html/2602.20478v1) --- Codified Context trigger tables, contextual routing
- [contextpatterns.com/patterns/grounding](https://contextpatterns.com/patterns/grounding/) --- anchoring directives, grounding pattern
- [Google ADK Architecture](https://raphaelmansuy.github.io/adk_training/blog/2025/12/08/context-engineering-google-adk-architecture/) --- context as compiled view per invocation
