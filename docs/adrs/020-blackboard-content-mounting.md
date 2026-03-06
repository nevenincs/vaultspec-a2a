---
adr_id: 020
title: Blackboard Content Mounting
date: 2026-03-03
status: Implemented
related:
  - docs/adrs/014-thread-metadata-context-injection.md
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/022-contextual-anchoring-graph-lifecycle.md
---

# ADR-020: Blackboard Content Mounting

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

ADR-019 extended `TeamState` to carry `vault_index` — a dict mapping doc-type to
`.vault/`-relative file paths. ADR-022 introduced per-invocation contextual anchoring:
a `SystemMessage` injecting the active feature tag, pipeline phase, and vault path
list into each supervisor and worker call.

The remaining gap is **content injection**: neither ADR reads the actual text of
`.vault/` documents. Workers currently have two options for accessing binding
documents (ADRs, research, plans):

1. Rely on the ADR-014 context preamble (a one-time `SystemMessage` listing paths,
   injected at thread creation). This is compacted away under `compact_context` and
   does not survive long sessions.
2. Issue tool calls to read files on demand. This wastes tokens on tool-call overhead
   and is unreliable — workers frequently skip reading binding ADRs when context is
   long and the original preamble has been compacted.

Without content mounting, the blackboard exists only as an index in state. Agents
are aware that `.vault/` documents exist (ADR-022) but cannot ground their outputs
in the actual document text without incurring tool-call overhead per invocation.

### 1.1 Relationship to ADR-022

ADR-022 anchoring and ADR-020 mounting are **complementary, not redundant**:

|                      | ADR-022 Anchoring                    | ADR-020 Mounting        |
| -------------------- | ------------------------------------ | ----------------------- |
| **Injects**          | Feature tag, phase, vault path list  | Actual file content     |
| **When**             | Every supervisor + worker invocation | Worker invocations only |
| **Token cost**       | ~200–400 tokens                      | Up to 20,000 tokens     |
| **Message position** | [2] — after persona                  | [3] — after anchoring   |

### 1.2 Prior Art

**Google ADK artifact handle pattern:** Agents hold lightweight handles (name +
summary) in state; content is expanded per-invocation outside state. ADR-019 vault
paths are exactly this handle pattern. ADR-020 is the expansion step.

**arXiv 2507.01701 §4.2:** Blackboard systems treat the context window as a scratch
pad. The control unit selects relevant blackboard segments and copies them into the
active agent's context before each invocation. Content selection is phase-scoped —
only segments relevant to the current phase are injected.

**MetaGPT (arXiv 2308.00352):** Roles receive the full shared environment as context.
MetaGPT's lesson for token management: inject only role-relevant documents, not the
entire shared state.

## 2. Decision

### 2.1 `mounted_context` State Field

A new transient field is added to `TeamState` (`src/vaultspec_a2a/core/state.py`):

```python
class TeamState(TypedDict):
    # ... existing fields ...

    # Transient: populated by mount_node before worker invocation.
    # Cleared to None by worker_node after reading.
    # Never persisted as content — only the string reference lives briefly in state.
    # None when active_feature is unset or vault_index is empty.
    mounted_context: NotRequired[str | None]
```

`mounted_context` uses last-write-wins (LangGraph default for plain typed fields).
It is intentionally transient — the string content represents assembled file text for
one invocation only. Its lifecycle is: `mount_node sets it → worker_node reads and
clears it`.

### 2.2 `mount_node` Implementation

A new module `src/vaultspec_a2a/core/nodes/mount.py` exposes a factory function
`create_mount_node(workspace_root)` that returns a closure-scoped `mount_node`.
The cache is private to each factory call, ensuring it is scoped to the lifetime
of the compiled graph — not shared across threads or sessions:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages.utils import count_tokens_approximately

from ..state import TeamState

__all__ = ["create_mount_node"]

_MOUNT_TOKEN_CEILING = 20_000
_DOC_SEPARATOR = "--- MOUNTED: {path} ---"
_DOC_FOOTER = "--- END ---"


def _select_paths(state: TeamState, workspace_root: Path) -> list[Path]:
    """Select documents to mount: ADRs always, then current-phase docs.

    Priority order (used when budget is exceeded):
    1. ADR documents (always binding, always first)
    2. Current-phase documents in filesystem sort order
    """
    vault_index: dict[str, list[str]] = state.get("vault_index") or {}
    phase: str | None = state.get("pipeline_phase")

    adr_paths = [workspace_root / p for p in vault_index.get("adr", [])]
    phase_paths = []
    if phase and phase != "adr":
        phase_paths = [workspace_root / p for p in vault_index.get(phase, [])]

    return adr_paths + phase_paths


def create_mount_node(workspace_root: Path) -> Callable:
    """Factory: returns a mount_node with a closure-scoped content cache.

    The cache is scoped to this factory call — one cache per compiled graph,
    not shared across threads or sessions.
    """
    cache: dict[tuple[str, float], str] = {}

    async def _read_vault_doc(path: Path) -> str:
        """Read a .vault/ document asynchronously with mtime-keyed cache.

        Both stat() and read_text() run inside asyncio.to_thread to avoid
        blocking the event loop. The cache check after the thread call means
        a cache hit on a second concurrent read for the same (path, mtime)
        is still possible; this is safe (idempotent) and acceptable for v1.
        """
        def _read_with_stat() -> tuple[tuple[str, float], str]:
            mtime = path.stat().st_mtime
            key = (str(path), mtime)
            return key, path.read_text(encoding="utf-8")

        key, content = await asyncio.to_thread(_read_with_stat)
        if key not in cache:
            cache[key] = content
        return cache[key]

    async def mount_node(state: TeamState) -> dict[str, Any]:
        """Preprocessing node: read .vault/ documents and assemble mounted_context.

        Runs between supervisor routing and worker invocation.
        Returns {"mounted_context": assembled_text} or {"mounted_context": None}
        when no feature is active or vault_index is empty.
        """
        if not state.get("active_feature"):
            return {"mounted_context": None}

        paths = _select_paths(state, workspace_root)
        if not paths:
            return {"mounted_context": None}

        blocks: list[str] = []
        tokens_used = 0

        for path in paths:
            if not path.exists():
                continue

            content = await _read_vault_doc(path)
            rel_path = str(path.relative_to(workspace_root))

            header = _DOC_SEPARATOR.format(path=rel_path)
            block = f"{header}\n{content}\n{_DOC_FOOTER}"
            block_tokens = count_tokens_approximately(block)

            remaining = _MOUNT_TOKEN_CEILING - tokens_used
            if block_tokens <= remaining:
                blocks.append(block)
                tokens_used += block_tokens
            elif remaining > 100:
                # Truncate to fit remaining budget (10% safety margin)
                ratio = remaining / block_tokens
                truncate_at = int(len(content) * ratio * 0.9)
                truncated = content[:truncate_at]
                block = f"{header}\n{truncated}\n[TRUNCATED]\n{_DOC_FOOTER}"
                blocks.append(block)
                break
            else:
                # No budget remaining — skip
                break

        if not blocks:
            return {"mounted_context": None}

        return {"mounted_context": "\n\n".join(blocks)}

    return mount_node
```

### 2.3 Graph Wiring

`compile_team_graph()` (`src/vaultspec_a2a/core/graph.py`) is amended to insert a mount node
between the supervisor routing edge and each worker node. The factory is called
once per worker at compilation time:

```python
from lib.core.nodes.mount import create_mount_node

# In compile_team_graph(), for each worker agent:
mount_fn = create_mount_node(workspace_root)
graph.add_node(f"mount_{agent_name}", mount_fn)
graph.add_edge(f"mount_{agent_name}", agent_name)

# Conditional edge routes supervisor → mount_{agent_name} instead of agent_name:
graph.add_conditional_edges(
    "supervisor",
    lambda state: state["next"],
    {
        agent_name: f"mount_{agent_name}"
        for agent_name in worker_agent_names
    } | {"FINISH": END},
)
```

Each worker gets its own `create_mount_node(workspace_root)` call, producing an
independent closure with its own cache. Cache lifetime matches graph compilation
lifetime — cleared when the graph is discarded.

### 2.4 Worker Integration

`create_worker_node()` (`src/vaultspec_a2a/core/nodes/worker.py`) is amended to read
`mounted_context` from state and inject it at message position [3]:

```python
async def worker_node(state: TeamState) -> dict[str, Any]:
    working_state = (
        compact_context(state, CONTEXT_LIMIT)
        if should_compact(state, CONTEXT_LIMIT)
        else state
    )

    anchoring = build_anchoring_context(state)   # ADR-022

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    if anchoring:
        messages.append(SystemMessage(content=anchoring))

    mounted = state.get("mounted_context")         # ADR-020
    if mounted:
        messages.append(SystemMessage(content=mounted))

    messages.extend(working_state["messages"])

    response = await model.ainvoke(messages, config)

    # Clear mounted_context after use — single-invocation only.
    return {
        "messages": [response],
        "mounted_context": None,
    }
```

### 2.5 Message Ordering

After both ADR-022 and ADR-020 are applied, the full message stack per worker
invocation is:

```
[1] SystemMessage(content=system_prompt)        ← TOML agent persona
[2] SystemMessage(content=anchoring_summary)    ← ADR-022: feature tag, phase, vault paths
[3] SystemMessage(content=mounted_content)      ← ADR-020: actual .vault/ file text
[4..] *working_state["messages"]                ← compacted conversation history
```

Position [3] sits between the lightweight metadata anchor and the conversation
history. This ordering is intentional: the LLM reads persona → what exists → what
it says → what was discussed. Binding documents at [3] are closer to the current
prompt than the persona definition, giving them higher effective attention weight
than if they were prepended before history.

### 2.6 Per-Invocation Cache

The cache is a `dict[tuple[str, float], str]` created inside `create_mount_node()`
and captured by the `mount_node` closure. It is keyed by `(absolute_path_str,
mtime_float)` and populated lazily on first read. When a worker writes a new
artifact to `.vault/`, the file's mtime changes and the old cache entry is
superseded on the next read — no explicit invalidation is needed.

Cache lifetime is scoped to the compiled graph: each `create_mount_node()` call
produces a fresh cache, and the cache is garbage-collected when the graph is
discarded. This prevents content leakage across unrelated threads or sessions.

**v1 trade-off:** `_read_with_stat()` reads the file even if the same `(path,
mtime)` was already cached by a concurrent `mount_node` call that started
simultaneously. This is safe (idempotent, last write wins) and acceptable for v1.
A pre-flight stat check before the thread call can be added later as an
optimisation without changing the interface.

## 3. Consequences

### Positive

- Workers receive actual binding document text on every invocation — no tool-call
  overhead, no reliance on agents remembering to read files.
- Phase-scoped selection (current phase + ADRs) limits injected content to what is
  relevant, avoiding context dilution from unrelated pipeline stages.
- The 20,000-token ceiling with priority-ordered truncation ensures the LLM always
  sees the most binding documents (ADRs) first, even under budget pressure.
- `mount_node` is independently testable — file I/O is isolated from LLM invocation.
- Closure-scoped cache eliminates redundant reads within a graph lifetime without
  leaking content across threads or sessions.
- mtime-keyed invalidation ensures the cache self-updates when workers write new
  artifacts.

### Negative / Trade-offs

- Mount node adds one extra graph node per worker, increasing graph compilation
  complexity. Star topologies with 5 workers gain 5 mount nodes.
- `mounted_context` is a transient string field in `TeamState`. While cleared after
  each use, the checkpointer serializes it briefly between `mount_node` completion
  and `worker_node` completion. For large mounted content (up to 20,000 tokens
  ≈ ~80 KB), this adds transient checkpoint write overhead.
- `_read_with_stat()` runs both stat and read in the thread call on every invocation
  for uncached paths. A pre-flight cache check (requiring a separate stat thread
  call) would avoid reads for cached paths but adds complexity; deferred to v2.
- The `ratio * 0.9` truncation heuristic is approximate. Exact token-level
  truncation would require tokenizing the content, which is slower. The 10% safety
  margin means the actual ceiling may be slightly under 20,000 tokens in practice.

## 4. Rejected Alternatives

### Inline mount logic in `worker_node`

Embedding file reads directly in `worker_node` conflates I/O with LLM invocation.
The combined node cannot be tested without mocking the LLM or the filesystem.
Rejected: separation of concerns.

### One `SystemMessage` per mounted document

Injecting each document as a separate `SystemMessage` increases the message list
length by N documents per invocation. A single concatenated block with explicit
`--- MOUNTED: path ---` separators is equally readable by the model and produces
fewer edge cases in message deduplication (LangGraph's `add_messages` reducer
deduplicates by ID). Rejected.

### Store content in `TeamState` persistently

Storing file content in a permanent `TeamState` field causes checkpoint bloat — a
50 KB document across 10 steps writes 500 KB to SQLite (ADR-019 §1.2). The
reference-in-state pattern (paths only, content ephemeral) is the LangGraph
canonical. Rejected.

### Mount all `.vault/` documents regardless of phase

Mounting all documents for a feature (all stages) at once injects research, ADRs,
plans, exec logs, and audit docs simultaneously. For a mature feature with 20+
documents this exceeds the 20,000-token ceiling immediately and injects irrelevant
context (e.g., audit docs during research phase). Phase-scoped selection is more
targeted. Rejected.

### Module-level cache

A module-level cache is shared across all threads and all compiled graphs in the
same process. It grows unbounded across sessions and leaks content between unrelated
features. Rejected in favour of closure-scoped cache (§2.6).

### Read files synchronously inside the async node

`path.read_text()` and `path.stat()` inside an `async def` node without
`asyncio.to_thread` block the event loop thread. All concurrent graph invocations
in the same process share this thread. Synchronous I/O is a correctness defect in
async LangGraph nodes. Rejected.

## 5. Implementation Constraints

- `mount_node` must be `async def`. Synchronous file reads or stat calls inside
  async nodes are forbidden (blocks event loop).
- Both `path.stat()` and `path.read_text()` must run inside `asyncio.to_thread`
  (wrapped together in `_read_with_stat()`).
- The cache must be closure-scoped (inside `create_mount_node()`). Module-level
  caches are forbidden for this use case.
- `mounted_context` is cleared by `worker_node` by returning `{"mounted_context": None}`
  in every code path, including exception handlers.
- Token counting uses `count_tokens_approximately` from `langchain_core.messages.utils`.
  Exact tokenization is not required.
- ADR documents are always selected first, regardless of current `pipeline_phase`.
  Phase documents are secondary.
- When a document exceeds remaining budget and `remaining > 100` tokens, truncate
  with a `[TRUNCATED]` marker. When `remaining <= 100`, skip entirely.
- `mount_node` returns `{"mounted_context": None}` (not omitting the key) in all
  early-return paths so the field is always explicitly set after the node runs.
- `workspace_root` is bound at factory call time via `create_mount_node(workspace_root)`.
- `src/vaultspec_a2a/core/nodes/mount.py` must declare `__all__ = ["create_mount_node"]`. Only
  the factory is public; helpers and constants are private.

## 6. Module Hierarchy Impact

```text
src/vaultspec_a2a/core/
├── state.py            AMENDED: mounted_context: NotRequired[str | None] added
├── graph.py            AMENDED: create_mount_node() called per worker;
│                       add_conditional_edges routes supervisor → mount_{name}
├── nodes/
│   ├── mount.py        NEW: create_mount_node() factory, mount_node closure,
│   │                   _read_vault_doc, _read_with_stat, _select_paths,
│   │                   _MOUNT_TOKEN_CEILING; __all__ = ["create_mount_node"]
│   └── worker.py       AMENDED: reads state.get("mounted_context"),
│                       appends at position [3], clears on return
├── tests/
│   ├── test_mount.py   NEW: mount_node unit tests (selection, truncation,
│   │                   cache scoping, no-feature skip, async I/O)
│   └── test_graph.py   AMENDED: graph wiring tests for mount_node insertion
```

## 7. References

- `src/vaultspec_a2a/core/state.py` — `TeamState` (mounted_context field added)
- `src/vaultspec_a2a/core/nodes/mount.py` — NEW (create_mount_node factory)
- `src/vaultspec_a2a/core/nodes/worker.py` — worker_node message construction (position [3])
- `src/vaultspec_a2a/core/graph.py` — compile_team_graph() mount node wiring
- [ADR-014](014-thread-metadata-context-injection.md) — workspace_root threading pattern
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) — vault_index, reference-in-state principle
- [ADR-022](022-contextual-anchoring-graph-lifecycle.md) — anchoring summary, message positions [1][2]
- [docs/research/2026-03-03-content-mounting-derisking.md](../research/2026-03-03-content-mounting-derisking.md) — token ceiling, async I/O, mount step pattern
- [arXiv 2507.01701](https://arxiv.org/abs/2507.01701) — blackboard content injection, phase-scoped selection
- [MetaGPT arXiv 2308.00352](https://arxiv.org/html/2308.00352v6) — role-relevant document injection
- [Google ADK Architecture](https://raphaelmansuy.github.io/adk_training/blog/2025/12/08/context-engineering-google-adk-architecture/) — artifact handle pattern, per-invocation expansion
