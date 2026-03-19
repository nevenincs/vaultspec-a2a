# Core Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/core/` — all 16 source files
**Baseline:** Last deep audit 2026-03-03 (LangGraph Alignment Sprint)

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

#### CRIT-01: Triple Rule Injection — Rules compiled 3x per node invocation

**Files:** `anchoring.py:64-84`, `nodes/supervisor.py:123-127`, `nodes/worker.py:154-157`

Rules are compiled and injected in THREE separate locations per single node invocation:

1. `build_anchoring_context()` in `anchoring.py` lines 64-84 — compiles rules via `RuleManager(settings.workspace_root)` and appends to the anchoring context string
2. `supervisor_node()` in `nodes/supervisor.py` lines 123-127 — compiles rules via `RuleManager(Path(_ws_root))` and appends as a separate SystemMessage
3. `worker_node()` in `nodes/worker.py` lines 154-157 — compiles rules via `RuleManager(Path(_ws_root))` and appends as a separate SystemMessage

**Impact:** Every LLM invocation receives the same rules content 2-3 times in the prompt, wasting tokens and confusing the model with redundant instructions. For a supervisor call, rules appear in both the anchoring SystemMessage AND a dedicated rules SystemMessage. For a worker call with active_feature set, rules appear in the anchoring context, a dedicated rules SystemMessage, AND potentially in mounted_context if rules files are in .vault/.

**Severity:** CRITICAL — direct token waste on every invocation, proportional to rules content size.

#### CRIT-02: Duplicate import block in anchoring.py

**File:** `anchoring.py:66-72`

Lines 66-72 contain a duplicated import block:

```python
    from .config import settings
    from .rules import RuleManager

    # Note: Using root from settings. In Docker this is usually /app.
    # ADR-028: Universal Rule Propagation
    from .config import settings
    from .rules import RuleManager
```python

The `from .config import settings` and `from .rules import RuleManager` imports are repeated verbatim. While Python's import system handles this gracefully (no runtime error), this is clearly copy-paste debris.

**Severity:** CRITICAL (code quality) — indicates the anchoring.py rule injection was bolted on hastily without review.

#### CRIT-03: anchoring.py uses `settings.workspace_root` while supervisor/worker use state-derived workspace_root

**File:** `anchoring.py:74` vs `nodes/supervisor.py:123-124` vs `nodes/worker.py:153-154`

`build_anchoring_context()` uses the global `settings.workspace_root` (line 74), but supervisor_node and worker_node derive workspace_root from `state.get("workspace_root")` or the closure-captured `workspace_root` parameter. These may differ:

- `settings.workspace_root` defaults to `./workspaces`
- The actual workspace_root is threaded from the API endpoint through to graph compilation

This means the anchoring context could compile rules from the wrong directory, or fail to find rules that exist in the actual thread workspace.

**Severity:** CRITICAL — rules from wrong workspace could be injected, or rules could silently fail to load.

---

### HIGH Findings

#### HIGH-01: RuleManager has no caching — filesystem I/O on every invocation

**File:** `rules.py` (entire class)

`RuleManager` performs full filesystem discovery (`glob("*.md")`) and reads every rule file on each `.compile()` call. With the triple injection from CRIT-01, this means 3 full filesystem scans + file reads per node invocation. Rule files are unlikely to change during a graph execution.

**Recommendation:** Add an LRU cache or mtime-based cache similar to mount.py's `_read_vault_doc` pattern.

#### HIGH-02: `_replace_plan` reducer accepts `None` despite type annotation

**File:** `state.py:56-64`

```python
def _replace_plan(
    existing: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    return new if new is not None else existing
```yaml

The type annotation says `new: list[dict[str, str]]` but the body checks `new is not None`. If LangGraph passes `None` as the new value (which the guard suggests is possible), the type annotation is wrong. If it can never be `None`, the guard is dead code.

#### HIGH-03: `workspace_root` not in TeamState but accessed via `state.get("workspace_root")`

**Files:** `nodes/supervisor.py:123`, `nodes/worker.py:153`

Both supervisor_node and worker_node call `state.get("workspace_root")`, but `TeamState` (state.py) does NOT define a `workspace_root` field. This means:

- The key is never set by any reducer
- It would only exist if manually injected into graph_input
- `state.get("workspace_root")` always returns `None` unless something outside the typed state sets it

The worker_node has a fallback (`workspace_root or state.get("workspace_root")`), but supervisor_node uses it as the sole source at line 123. The supervisor's closure does not capture `workspace_root` from graph compilation.

**Impact:** Supervisor node never loads rules from state-derived workspace (always falls through to the anchoring path which uses `settings.workspace_root` — see CRIT-03).

#### HIGH-04: Pipeline and pipeline_loop topologies don't wire mount nodes

**File:** `graph.py:486-568` (`_compile_pipeline`), `graph.py:644-723` (`_compile_pipeline_loop`)

Only `_compile_star` (line 463-465) creates and wires `mount_{agent_id}` nodes between supervisor routing and worker invocation. The `_compile_pipeline` and `_compile_pipeline_loop` functions wire workers directly with `add_edge`.

This means workers in pipeline/pipeline_loop topologies never receive mounted vault context, even when `active_feature` and `vault_index` are set in state.

**Impact:** ADR-020 (blackboard content mounting) is only functional for star topology.

#### HIGH-05: Pipeline/pipeline_loop workers don't receive `workspace_root` or `feature_tag`

**File:** `graph.py:547-552` vs `graph.py:443-449`

In `_compile_star`, `create_worker_node` is called with `workspace_root=workspace_root` and `feature_tag=feature_tag`. In `_compile_pipeline` (line 547) and `_compile_pipeline_loop` (line 684), these parameters are omitted, meaning they default to `None`.

**Impact:** Task queue drain (ADR-021) is non-functional for pipeline/pipeline_loop topologies.

#### HIGH-06: `_ROLE_TO_PHASE` contains "researcher" but graph.py line 56 already fixed

**File:** `graph.py:54-60`

The memory notes say `"researcher"` entry was removed from `_ROLE_TO_PHASE`, but it's still present:

```python
_ROLE_TO_PHASE: dict[str, str] = {
    "researcher": "research",
    ...
}
```text

This is actually correct per the code — `"researcher"` maps to `"research"` phase. The memory note about removal was likely about a different map. No action needed, but documenting for clarity.

**Status:** FALSE POSITIVE — "researcher" is correct here.

---

### MEDIUM Findings

#### MED-01: `compact_context` returns `dict(state)` which loses TypedDict type safety

**File:** `context.py:76,80,140`

`dict(state)` creates a plain `dict` from the `TeamState` TypedDict. The `# type: ignore[return-value]` comments acknowledge this. While functional, it means downstream code loses type-checked access to TeamState fields.

#### MED-02: `_append_validation_errors` uses empty list as clear signal

**File:** `state.py:83-90`

```python
def _append_validation_errors(existing: list[str], new: list[str]) -> list[str]:
    if not new:
        return []
    return existing + new
```python

An empty `new` list means "clear all errors" rather than "no change". This is a non-obvious convention that could surprise callers who pass `validation_errors=[]` expecting no-op behavior.

#### MED-03: `_filter_queue_content` separator detection is fragile

**File:** `task_queue.py:44-49`

The separator row detection checks if `stripped.replace("|","").replace("-","").replace(" ","")` equals `set()`. This works for `|---|---|---|` but would also match `|- -|` or other degenerate patterns. Additionally, `set()` comparison with `== set()` should be `== ""` or `len(...) == 0` since the result of the set operation on an empty string is `set()` but on `""` it would be different.

Actually: `set("")` returns `set()`, and `set(stripped...)` where all chars are removed returns `set()`. This is correct but non-obvious.

#### MED-04: `_evict_oldest` in aggregator sorts entire dict on every eviction

**File:** `aggregator.py:105-112`

When the debounce map exceeds 1000 entries, `_evict_oldest` sorts all entries by timestamp. For 1000+ entries this is O(n log n) on every new entry. A more efficient approach would use `collections.OrderedDict` or a min-heap.

#### MED-05: `discover_team_preset_ids` not exported from `__init__.py`

**File:** `team_config.py:79-87` vs `core/__init__.py`

`discover_team_preset_ids` is listed in `team_config.py.__all__` but is NOT imported or exported from `core/__init__.py`. Consumers must deep-import from `core.team_config` directly, violating the facade pattern (CLAUDE.md architectural patterns).

#### MED-06: `PHASE_ORDER` exported twice with different names

**File:** `phase.py:8-10`

```python
PHASE_ORDER: list[str] = [...]
_PHASE_ORDER = PHASE_ORDER
```python

`PHASE_ORDER` is the public name (in `__all__`), but `_PHASE_ORDER` (private alias) is used internally. The alias adds no value — it's the same object.

#### MED-07: `StreamableGraph` protocol not exported from `core/__init__.py`

**File:** `aggregator.py:63` — `__all__ = ["EventAggregator", "StreamableGraph"]`

`StreamableGraph` is declared in `aggregator.__all__` but the lazy import in `core/__init__.py` only loads `EventAggregator`. `StreamableGraph` is not accessible via the facade.

**Note:** Memory says this was fixed in a previous sprint, but it's not present in the current `__init__.py` lazy imports or `__all__`.

---

### LOW Findings

#### LOW-01: `AgentConfigNotFoundError` docstring references `lib/core/presets/`

**File:** `exceptions.py:244-257`

The docstring and error message still reference `lib/core/presets/agents/` instead of the migrated `src/vaultspec_a2a/core/presets/agents/` path. Same for `TeamConfigNotFoundError` at line 265-277.

#### LOW-02: `_VAULT_STAGE_PATTERNS` duplicated between `graph.py` and `metadata.py`

**Files:** `graph.py:42-48`, `metadata.py:106-113`

Both files define the same stage pattern mapping independently. A single source of truth would prevent drift.

#### LOW-03: `_QUEUE_PHASES` duplicated between `mount.py` and `task_queue.py`

**Files:** `mount.py:22`, `task_queue.py:14`

Both define `_QUEUE_PHASES = frozenset({"plan", "exec"})`.

#### LOW-04: `mount.py` imports private `_filter_queue_content` from `task_queue.py`

**File:** `mount.py:15`

```python
from ..task_queue import _filter_queue_content
```python

Importing a private function (leading underscore) from another module breaks encapsulation. This should be made public or moved to a shared location.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 3     | Triple rule injection, duplicate imports, workspace_root mismatch |
| HIGH     | 5     | No RuleManager cache, missing TeamState field, pipeline topology gaps |
| MEDIUM   | 7     | Type safety, facade gaps, fragile parsing, debounce perf |
| LOW      | 4     | Stale paths, code duplication, private import |

### Recommended Fix Priority

1. **CRIT-01 + CRIT-02 + CRIT-03**: Consolidate rule injection to a single point. Remove rules from `anchoring.py` entirely — let supervisor/worker nodes handle it with their properly-scoped workspace_root. Fix the duplicate imports.
2. **HIGH-03 + HIGH-04 + HIGH-05**: Decide whether pipeline topologies should support vault mounting and task queues. If yes, wire mount nodes and pass workspace_root/feature_tag. If not, document the limitation.
3. **HIGH-01**: Add caching to RuleManager.
4. **MED-05 + MED-07**: Fix facade exports.

---

## Cycle 2 — Re-audit (2026-03-06)

### Verified Fixes

| Finding | Description | Status |
|---------|-------------|--------|
| CRIT-01 | Triple rule injection | **FIXED** -- RuleManager removed from anchoring.py; only in supervisor.py:125 and worker.py:155 |
| CRIT-02 | Duplicate imports in anchoring.py | **FIXED** -- anchoring.py is clean (no RuleManager or settings imports) |
| CRIT-03 | anchoring.py uses settings.workspace_root | **FIXED** -- anchoring.py no longer accesses workspace_root at all |
| HIGH-06 | `_ROLE_TO_PHASE` "researcher" entry | FALSE POSITIVE -- confirmed correct |

### Still Open

| Finding | Severity | Status |
|---------|----------|--------|
| HIGH-01 | RuleManager no caching | **OPEN** (task #10) |
| HIGH-02 | `_replace_plan` accepts None despite annotation | **OPEN** |
| HIGH-03 | `workspace_root` not in TeamState | **OPEN** -- but workspace_root is now in TeamState (state.py:159 comment) |
| HIGH-04 | Pipeline/pipeline_loop don't wire mount nodes | **OPEN** (task #8 completed -- need verification) |
| HIGH-05 | Pipeline/pipeline_loop missing workspace_root/feature_tag | **OPEN** (task #8 completed -- need verification) |
| MED-01 through MED-07 | Various | **OPEN** |
| LOW-01 through LOW-04 | Various | **OPEN** |

### Additional Verified Fixes

| Finding | Description | Status |
|---------|-------------|--------|
| HIGH-03 | `workspace_root` not in TeamState | **FIXED** -- `state.py:160`: `workspace_root: NotRequired[str \| None]` |
| HIGH-04 | Pipeline/pipeline_loop don't wire mount nodes | **FIXED** -- `graph.py:564-584` (pipeline) and `graph.py:715-741` (pipeline_loop) now wire mount nodes |
| HIGH-05 | Pipeline/pipeline_loop missing workspace_root/feature_tag | **FIXED** -- `graph.py:560-561` (pipeline) and `graph.py:708-709` (pipeline_loop) now pass both params |
| MED-05 | `discover_team_preset_ids` not in facade | **FIXED** -- `__init__.py:114,196` |
| MED-07 | `StreamableGraph` not in facade | **FIXED** -- `__init__.py:130,169` (lazy import) |

### Cycle 2 Summary

- 3 CRIT: ALL FIXED (task #7)
- 5 HIGH: 1 false positive (HIGH-06), 4 fixed (HIGH-03/04/05), 1 still open (HIGH-01 task #10)
- HIGH-02 (`_replace_plan` None guard) still open but low risk
- 7 MED: 2 fixed (MED-05, MED-07), 5 still open
- 4 LOW: all still open

**Remaining open: 0 CRIT, 2 HIGH (HIGH-01 + HIGH-02), 5 MED, 4 LOW**
