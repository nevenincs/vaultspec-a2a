# LangGraph Interrupt ID System — Research Findings

**Date**: 2026-03-19
**Context**: Grounding for Phase 5 (deterministic permission IDs)
**Source**: LangGraph source code analysis (knowledge/repositories/langgraph/)

---

## Key Finding

**LangGraph provides deterministic, built-in interrupt IDs natively
(since v0.4.0, current in v0.6.0+).**

The `Interrupt` dataclass has an `id: str` field generated from the
checkpoint namespace via xxHash:

```python
@classmethod
def from_ns(cls, value: Any, ns: str) -> Interrupt:
    return cls(value=value, id=xxh3_128_hexdigest(ns.encode()))
```

The ID is a **32-character hex string** that is stable across restarts,
re-inspections, and retries — it depends only on the graph hierarchy
path, not on time or randomness.

## Checkpoint Coordinate System

| Key | Description |
|-----|-------------|
| `thread_id` | Primary conversation/session key |
| `checkpoint_ns` | Graph hierarchy path (empty for root, `:task-uuid` for tasks) |
| `checkpoint_id` | UUID6 (time-sortable) for a specific checkpoint |

## Interrupt ID Determinism Chain

1. Root graph: `checkpoint_ns = ""`
2. Task within root: `checkpoint_ns = f":{task_id}"`
3. `interrupt()` function hashes the namespace:
   `id = xxh3_128_hexdigest(checkpoint_ns.encode())`

The same interrupt in the same graph position always produces the
same ID.

## Multiple Interrupts in One Node

Multiple `interrupt()` calls within a single node share the **same**
`Interrupt.id` (same `checkpoint_ns`). They are distinguished by an
**ordinal counter** (`scratchpad.interrupt_counter`), matched by
position during resume.

**Implication for permission IDs**: If multiple interrupts exist in
one node, the position-based fallback
`{thread_id}:task{N}:int{M}` provides differentiation.

## Resume Mechanism

Two modes:

### Single value (positional)

```python
Command(resume="some value")
```

Only works when exactly ONE pending interrupt exists.

### Dict keyed by interrupt IDs (v0.4.0+)

```python
Command(resume={"<interrupt_id_hex>": value})
```

The resume map key is `xxh3_128_hexdigest(task_checkpoint_ns.encode())`
— the **same hash** used for the interrupt ID. This makes the
round-trip deterministic.

## Impact on Our Implementation

Our Phase 5 priority chain in `_emit_interrupt_events()`:

```python
request_id = str(
    payload.get("request_id")           # 1. ACP worker payload
    or getattr(interrupt_obj, "id", None)  # 2. Native LangGraph ID
    or f"{thread_id}:task{N}:int{M}"    # 3. Position-based fallback
)
```

- **Priority 2** will be used in most cases — it IS the native
  deterministic ID from LangGraph >= 0.4.0
- **Priority 3** is the safety net for edge cases where both payload
  and interrupt object lack an ID
- The dedup guard (`if request_id in self._pending_permissions:
  continue`) prevents re-emission regardless of which priority fires

## Source Files

| File | Content |
|------|---------|
| `langgraph/types.py` | `Interrupt` class, `interrupt()` function |
| `langgraph/pregel/_algo.py` | `_scratchpad()`, namespace hash, resume map |
| `langgraph/pregel/_loop.py` | `Command(resume=...)` processing |
| `langgraph/_internal/_scratchpad.py` | `PregelScratchpad` with ordinal counter |
| `langgraph/checkpoint/base/__init__.py` | `Checkpoint` TypedDict |
