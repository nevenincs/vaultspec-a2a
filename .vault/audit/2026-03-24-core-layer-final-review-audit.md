---
tags:
  - '#audit'
  - '#core-layer'
date: '2026-03-24'
related:
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# core-layer final review — re-exports, shims, duplicates, layer violations

Independent exhaustive audit of Layer 1 (`thread/`, `context/`, `team/`, `graph/`, `lifecycle/`, `domain_config.py`) and Layer 1.5 (`streaming/`), plus `utils/enums.py`.

---

## 1. Re-export shims (files whose sole purpose is `from X import Y as Y`)

### `src/vaultspec_a2a/thread/__init__.py`

**VIOLATION — PARTIAL.** The file re-exports every symbol from `thread/errors.py` and `thread/models.py` using `X as X` syntax. Most of these are clean façade exports (the canonical definition lives in the submodule and `__init__` simply surfaces it). However, line 29–34 carries an explicit admission:

```python
# GitWorkspaceError is re-exported for convenience, but semantically belongs
# to the workspace layer — not the thread facade.
```

The comment acknowledges the symbol does not semantically belong here. This is a convenience shim for `GitWorkspaceError`. All other exports in this file are legitimate façade re-exports of types that canonically live in `thread/errors.py` and `thread/models.py` — **OK**. The `GitWorkspaceError` re-export is a documented exception to the rule but is still a shim by the author's own admission — **VIOLATION (minor, documented)**.

### `src/vaultspec_a2a/team/__init__.py`

**VIOLATION — SHADOW IMPORT CHAIN.** `team/__init__.py` re-exports `AgentConfigNotFoundError` and `TeamConfigNotFoundError`. These originate in `thread/errors.py`. The chain is:

```
thread/errors.py  →  team/team_config.py (imports, does NOT define)
                  →  team/__init__.py    (re-exports from team_config.py)
```

`team_config.py` does not define these classes; it imports them from `vaultspec_a2a.thread.errors` and passes them through. `team/__init__.py` then re-exports them again. Callers importing from `vaultspec_a2a.team` get symbols whose canonical home is `vaultspec_a2a.thread`. This creates two public paths to the same object — **VIOLATION**.

### `src/vaultspec_a2a/graph/__init__.py`

**OK.** Exposes `build_initial_vault_index` and `compile_team_graph` which are defined in `graph/compiler.py`. This is a standard façade — single canonical definition, single public surface.

### `src/vaultspec_a2a/graph/nodes/__init__.py`

**OK.** Exposes `create_supervisor_node` and `create_worker_node` from their respective submodules. These are their canonical definitions. Standard façade.

### `src/vaultspec_a2a/context/__init__.py`

**OK.** All symbols are canonically defined in submodules (`anchoring.py`, `metadata.py`, `preamble.py`, `rules.py`, `stage.py`, `token_budget.py`). No cross-package re-export chains.

### `src/vaultspec_a2a/lifecycle/__init__.py`

**OK.** Two exports (`ReconciliationAction`, `compute_reconciliation_actions`) from `reconciliation.py` — their canonical home.

### `src/vaultspec_a2a/streaming/__init__.py`

**OK.** `EventAggregator` from `aggregator.py`, `SequencedEvent`/`StreamableGraph`/`classify_tool_kind` from `types.py` — all canonical.

---

## 2. Duplicated definitions

### `AgentState` (utils) vs `AgentLifecycleState` (graph)

**OK — distinct types.** `utils/enums.py:AgentState` (INIT/READY/RUNNING/ERROR/DONE) tracks internal worker process lifecycle. `graph/enums.py:AgentLifecycleState` (SUBMITTED/IDLE/WORKING/INPUT_REQUIRED/…) tracks observable frontend state per ADR-003. The docstring in `graph/enums.py` line 28 explicitly acknowledges the distinction: *"Distinct from `vaultspec_a2a.utils.enums.AgentState` which tracks internal process lifecycle."* Different purposes, no duplication.

### `class Provider` — two files

- `graph/enums.py:98` — **canonical Layer 1 definition** (CLAUDE/GEMINI/MOCK/OPENAI/ZHIPU as StrEnum). Docstring explicitly says "canonical Layer 1 definitions."
- `providers/factory.py:235` — `class ProviderFactory` — **different class, different purpose**. This is a factory, not an enum. Name collision in the grep output only; not a duplicate definition.

**OK.** No duplication.

### `class Model` — one location

Only `graph/enums.py:108`. `utils/enums.py` contains no `Model` class. **OK.**

### `AgentConfigNotFoundError` — one definition, two import paths

Defined once in `thread/errors.py:257`. But accessible via two public paths: `vaultspec_a2a.thread` and `vaultspec_a2a.team`. See shadow import chain finding above — **VIOLATION (same as §1 team/__init__)**.

### `TeamConfigNotFoundError` — same pattern

Defined once in `thread/errors.py:278`. Accessible via `vaultspec_a2a.thread` and `vaultspec_a2a.team` — **VIOLATION (same)**.

---

## 3. Shadow imports

### `team/team_config.py` importing from `thread/errors`

```python
from vaultspec_a2a.thread.errors import (
    AgentConfigNotFoundError,
    ConfigError,
    TeamConfigNotFoundError,
)
```

`team_config.py` imports and uses these types as type annotations and raise sites. It does not re-export them directly (no `__all__` inclusion). However `team/__init__.py` then re-exports `AgentConfigNotFoundError` and `TeamConfigNotFoundError` by pulling them from `team_config.py` — creating the shadow path. The cross-package import itself (team → thread) is within Layer 1 and is an acceptable intra-layer dependency. The issue is the subsequent re-export surfacing them under `vaultspec_a2a.team` — **VIOLATION** as noted in §1 and §2.

---

## 4. Stale docstrings

Grep for "backwards.compat\|re-export\|shim\|canonical source" in scope:

- `thread/__init__.py:29` — comment: *"GitWorkspaceError is re-exported for convenience, but semantically belongs to the workspace layer."* This is a live, accurate comment on an intentional shim — not stale, but confirms the violation.
- `thread/tests/test_errors.py:28,365` — test file, out of scope for production audit.
- `team/tests/test_team_config.py:579` — test file, out of scope.
- `streaming/tests/test_aggregator.py:998` — test file, out of scope.
- `graph/enums.py:28` — docstring says *"Distinct from `vaultspec_a2a.utils.enums.AgentState`"* — this is accurate, informative, not stale. **OK.**
- `graph/events.py:7` — docstring says *"Core never imports from `api.schemas` — the dependency arrow points outward."* — accurate, not stale. **OK.**
- `thread/errors.py:150` — comment: *"so that Layer 1 code never imports from the providers layer."* Accurate design commentary. **OK.**

**No stale docstrings found.**

---

## 5. Unused imports (for re-export purposes only)

### `team/team_config.py` — `AgentConfigNotFoundError`, `TeamConfigNotFoundError`

These are imported from `thread/errors` and used within `team_config.py` as raise sites (`raise AgentConfigNotFoundError(...)`, `raise TeamConfigNotFoundError(...)`). They are not imported solely for re-export — they have functional use inside the module. **OK as imports.** The violation is in `team/__init__.py` re-exporting them.

No other unused-for-re-export imports found in scope.

---

## 6. Layer 1 → outside imports

All absolute `vaultspec_a2a.*` imports found in Layer 1/1.5 non-test files:

| File | Import | Classification |
|---|---|---|
| `context/anchoring.py` | `vaultspec_a2a.domain_config` | **OK** — domain_config is Layer 1 |
| `context/metadata.py` | `vaultspec_a2a.domain_config` | **OK** |
| `context/token_budget.py` | `vaultspec_a2a.domain_config` | **OK** |
| `context/token_budget.py` | `vaultspec_a2a.thread.state` | **OK** — intra-layer |
| `team/team_config.py` | `vaultspec_a2a.graph.enums` | **OK** — intra-layer |
| `team/team_config.py` | `vaultspec_a2a.thread.errors` | **OK** — intra-layer |
| `graph/compiler.py` | `vaultspec_a2a.domain_config` | **OK** |
| `graph/compiler.py` | `vaultspec_a2a.thread.errors` | **OK** — intra-layer |
| `graph/compiler.py` | `vaultspec_a2a.thread.state` | **OK** — intra-layer |
| `graph/nodes/supervisor.py` | `vaultspec_a2a.context.*` | **OK** — intra-layer |
| `graph/nodes/supervisor.py` | `vaultspec_a2a.domain_config` | **OK** |
| `graph/nodes/supervisor.py` | `vaultspec_a2a.thread.state` | **OK** — intra-layer |
| `graph/nodes/worker.py` | `vaultspec_a2a.context.*` | **OK** — intra-layer |
| `graph/nodes/worker.py` | `vaultspec_a2a.domain_config` | **OK** |
| `graph/nodes/worker.py` | `vaultspec_a2a.thread.errors` | **OK** — intra-layer |
| `graph/nodes/worker.py` | `vaultspec_a2a.thread.state` | **OK** — intra-layer |
| `graph/tools/task_queue.py` | `vaultspec_a2a.domain_config` | **OK** |
| `graph/nodes/vault_reader.py` | `vaultspec_a2a.domain_config` | **OK** |
| `streaming/subscribers.py` | `vaultspec_a2a.thread.errors` | **OK** — intra-layer |

No Layer 1 or 1.5 file imports from `utils/`, `control/`, `api/`, `database/`, `providers/`, `telemetry/`, or `worker/` in production code.

---

## Summary of violations

| # | Location | Type | Severity |
|---|---|---|---|
| V-01 | `thread/__init__.py:29-34` | Re-export shim — `GitWorkspaceError` admitted not to belong here | Minor |
| V-02 | `team/__init__.py` (via `team_config.py`) | Shadow import chain — `AgentConfigNotFoundError` and `TeamConfigNotFoundError` surfaced under `vaultspec_a2a.team` despite canonical home in `thread/errors` | Moderate |

---

## Verdict: NOT CLEAN

Two violations found. V-01 is minor and explicitly documented by the author. V-02 is moderate: two error classes that canonically belong to `thread/errors` are accessible via a second public path `vaultspec_a2a.team`, creating a shadow import chain through `team_config.py` → `team/__init__.py`. Callers should import these directly from `vaultspec_a2a.thread`. The `team/__init__.py` re-exports of `AgentConfigNotFoundError` and `TeamConfigNotFoundError` should be removed, and any external callers updated to import from `vaultspec_a2a.thread`.
